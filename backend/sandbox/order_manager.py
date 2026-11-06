"""Transactional paper-order ledger.

Mutations lock the account and commit order status, trade, position and cash
together. Validation and margin lookups share that transaction's connection;
the execution engine supplies a quote and conditions are rechecked here.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
import math
import random
import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.models.sandbox import SandboxOrder, SandboxTrade
from backend.sandbox._db import session_scope
from backend.sandbox._session import session_start_ist
from backend.sandbox import fund_manager

logger = logging.getLogger(__name__)


def new_orderid() -> str:
    """Sandbox orderid in openalgo's format: ``YYMMDD`` prefix + 8-digit
    sequence (6-digit microseconds + 2-digit random). Sortable by date and
    free of vendor prefixes — matches openalgo's
    ``OrderManager._generate_order_id`` exactly so reports / logs / tooling
    that splits on the date prefix work the same way."""
    now = datetime.now()
    return f"{now.strftime('%y%m%d')}{now.microsecond:06d}{random.randint(0, 99):02d}"


def new_tradeid() -> str:
    """Trade id matching openalgo: ``TRADE-YYYYMMDD-HHMMSS-<8 hex>``."""
    now = datetime.now()
    return f"TRADE-{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(4).upper()}"


class OrderValidationError(ValueError):
    pass


def create_order(
    *,
    user_id: int,
    symbol: str,
    exchange: str,
    action: str,
    quantity: int,
    pricetype: str,
    product: str,
    price: float = 0.0,
    trigger_price: float = 0.0,
    strategy: str | None = None,
    margin_blocked: float = 0.0,
    initial_status: str = "open",
    rejection_reason: str | None = None,
    reference_price: float | None = None,
    db: Session | None = None,
) -> SandboxOrder:
    orderid = new_orderid()
    owns_session = db is None
    with (session_scope() if owns_session else nullcontext(db)) as db:
        funds = fund_manager.ensure_fund_row(db, user_id)
        if initial_status in ("open", "trigger_pending"):
            from backend.paper.policy import order_access
            allowed, reason = order_access(db=db, user_id=user_id, symbol=symbol, exchange=exchange,
                product=product, action=action.upper(), quantity=quantity)
            if not allowed:
                initial_status, rejection_reason = "rejected", reason
                margin_blocked = 0.0
        if initial_status in ("open", "trigger_pending"):
            margin_blocked = fund_manager.required_order_margin(db, user_id, symbol, exchange,
                product, action, quantity, reference_price if reference_price is not None else price)
            from backend.sandbox.brokerage import quote_charge
            try:
                quote = quote_charge(db, user_id, reference_price if reference_price is not None else price, quantity)
            except ValueError as error:
                initial_status, rejection_reason, margin_blocked = "rejected", str(error), 0.0
                quote = None
            fee = quote.fee_paise / 100 if quote else 0.0
            if initial_status != "rejected" and margin_blocked > 0 and margin_blocked + fee > funds.available:
                initial_status = "rejected"
                rejection_reason = f"Insufficient virtual funds: margin ₹{margin_blocked:.2f} plus 4% brokerage ₹{fee:.2f}; available ₹{funds.available:.2f}"
                margin_blocked = 0.0
            elif initial_status != "rejected":
                funds.available = round(funds.available - margin_blocked, 2)
                funds.used_margin = round(funds.used_margin + margin_blocked, 2)
        row = SandboxOrder(
            user_id=user_id,
            orderid=orderid,
            symbol=symbol,
            exchange=exchange,
            action=action.upper(),
            quantity=int(quantity),
            pricetype=pricetype.upper(),
            product=product.upper(),
            price=float(price),
            trigger_price=float(trigger_price),
            strategy=strategy,
            margin_blocked=float(margin_blocked),
            status=initial_status,
            rejection_reason=rejection_reason,
        )
        db.add(row)
        db.flush()
        if owns_session:
            db.expunge(row)
    return row


def get_order(user_id: int, orderid: str) -> SandboxOrder | None:
    with session_scope() as db:
        row = db.execute(
            select(SandboxOrder).where(
                SandboxOrder.user_id == user_id, SandboxOrder.orderid == orderid
            )
        ).scalar_one_or_none()
        if row is not None:
            db.expunge(row)
        return row


def list_orders(user_id: int, *, all_history: bool = False) -> list[SandboxOrder]:
    """Return the user's sandbox orderbook.

    Filtered to the *current session* by default — orders placed before
    the last ``session_expiry_time`` boundary (00:00 IST default) are
    hidden so the orderbook view rolls over cleanly each day instead of
    growing forever. Pass ``all_history=True`` for diagnostics or audit
    paths that want the full history.
    """
    with session_scope() as db:
        stmt = select(SandboxOrder).where(SandboxOrder.user_id == user_id)
        if not all_history:
            stmt = stmt.where(SandboxOrder.order_timestamp >= session_start_ist())
        stmt = stmt.order_by(SandboxOrder.order_timestamp.desc())
        rows = db.execute(stmt).scalars().all()
        for r in rows:
            db.expunge(r)
        return list(rows)


def list_trades(user_id: int, *, all_history: bool = False) -> list[SandboxTrade]:
    """Return the user's sandbox tradebook.

    Same session-window filter as :func:`list_orders` — yesterday's
    fills don't pollute today's view. ``all_history=True`` returns the
    full table.
    """
    with session_scope() as db:
        stmt = select(SandboxTrade).where(SandboxTrade.user_id == user_id)
        if not all_history:
            stmt = stmt.where(SandboxTrade.timestamp >= session_start_ist())
        stmt = stmt.order_by(SandboxTrade.timestamp.desc())
        rows = db.execute(stmt).scalars().all()
        for r in rows:
            db.expunge(r)
        return list(rows)


def list_pending_orders() -> list[SandboxOrder]:
    """For the execution engine. Returns open / trigger_pending across all users."""
    with session_scope() as db:
        rows = (
            db.execute(
                select(SandboxOrder).where(
                    SandboxOrder.status.in_(("open", "trigger_pending"))
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            db.expunge(r)
        return list(rows)


def count_all_orders() -> int:
    """Used by /api/v1/analyzerstatus `total_logs` field."""
    from sqlalchemy import func

    with session_scope() as db:
        return db.execute(
            select(func.count()).select_from(SandboxOrder)
        ).scalar() or 0


def modify_order(user_id: int, orderid: str, *, quantity: int | None = None,
                 price: float | None = None, trigger_price: float | None = None,
                 pricetype: str | None = None) -> SandboxOrder | None:
    from backend.sandbox.order_validation import validate_order
    from backend.sandbox.quote_helper import get_ltp
    with session_scope() as db:
        funds = fund_manager.ensure_fund_row(db, user_id)
        row = db.scalar(select(SandboxOrder).where(SandboxOrder.user_id == user_id,
            SandboxOrder.orderid == orderid).with_for_update())
        if row is None or row.status not in ("open", "trigger_pending"):
            return None
        values = dict(user_id=user_id, symbol=row.symbol, exchange=row.exchange,
            product=row.product, action=row.action,
            quantity=row.quantity if quantity is None else quantity,
            price=row.price if price is None else price,
            trigger_price=row.trigger_price if trigger_price is None else trigger_price,
            pricetype=row.pricetype if pricetype is None else pricetype.upper())
        ok, reason, _ = validate_order(**values, db=db, remaining_quantity=values["quantity"] - row.filled_quantity)
        if not ok:
            raise OrderValidationError(reason)
        if values["quantity"] <= row.filled_quantity:
            raise OrderValidationError("quantity must exceed the already filled quantity")
        reference = values["price"] if values["pricetype"] in ("LIMIT", "SL") else get_ltp(user_id, row.symbol, row.exchange)
        if reference is None or not math.isfinite(reference) or reference <= 0:
            raise OrderValidationError("No fresh price available")
        margin = fund_manager.required_order_margin(db, user_id, row.symbol, row.exchange,
            row.product, row.action, values["quantity"] - row.filled_quantity, reference)
        difference = round(margin - row.margin_blocked, 2)
        from backend.sandbox.brokerage import quote_charge
        try:
            charge = quote_charge(db, user_id, reference, values["quantity"] - row.filled_quantity)
        except ValueError as error:
            raise OrderValidationError(str(error)) from None
        fee = charge.fee_paise / 100 if charge else 0.0
        if margin > 0 and difference + fee > funds.available:
            raise OrderValidationError("Insufficient sandbox funds for margin and brokerage")
        funds.available = round(funds.available - difference, 2)
        funds.used_margin = round(funds.used_margin + difference, 2)
        for field in ("quantity", "price", "trigger_price", "pricetype"):
            setattr(row, field, values[field])
        row.margin_blocked = margin
        row.status = "trigger_pending" if row.pricetype in ("SL", "SL-M") else "open"
        db.flush()
        db.expunge(row)
        return row


def cancel_order(user_id: int, orderid: str, *, reason: str | None = None) -> SandboxOrder | None:
    with session_scope() as db:
        funds = fund_manager.ensure_fund_row(db, user_id)
        row = db.scalar(select(SandboxOrder).where(SandboxOrder.user_id == user_id,
            SandboxOrder.orderid == orderid).with_for_update())
        if row is None or row.status not in ("open", "trigger_pending"):
            return None
        released = min(row.margin_blocked, funds.used_margin)
        funds.used_margin = round(funds.used_margin - released, 2)
        funds.available = round(funds.available + released, 2)
        row.margin_blocked = 0.0
        row.status = "cancelled"
        row.rejection_reason = reason
        db.flush()
        db.expunge(row)
        return row


def list_cancellable_orders(user_id: int) -> list[SandboxOrder]:
    with session_scope() as db:
        rows = (
            db.execute(
                select(SandboxOrder).where(
                    SandboxOrder.user_id == user_id,
                    SandboxOrder.status.in_(("open", "trigger_pending")),
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            db.expunge(r)
        return list(rows)


def fill(user_id: int, orderid: str, fill_price: float,
         fill_quantity: int | None = None, *, ltp: float | None = None, db: Session | None = None
         ) -> tuple[SandboxOrder | None, SandboxTrade | None]:
    """Claim the order and commit its trade, position and cash in one transaction."""
    from backend.sandbox.order_validation import validate_order
    from backend.sandbox.position_manager import apply_fill
    owns_session = db is None
    with (session_scope() if owns_session else nullcontext(db)) as db:
        funds = fund_manager.ensure_fund_row(db, user_id)
        row = db.scalar(select(SandboxOrder).where(SandboxOrder.user_id == user_id,
            SandboxOrder.orderid == orderid).with_for_update())
        if row is None or row.status not in ("open", "trigger_pending"):
            return None, None
        if ltp is not None:
            price = fill_price_for(row, ltp)
            if price is None:
                return None, None
            fill_price = price
        remaining = row.quantity - row.filled_quantity
        qty = remaining if fill_quantity is None else fill_quantity
        ok, reason, _ = validate_order(user_id=user_id, symbol=row.symbol,
            exchange=row.exchange, action=row.action, quantity=qty, product=row.product,
            pricetype=row.pricetype, price=row.price, trigger_price=row.trigger_price, db=db)
        if not ok or qty > remaining or not math.isfinite(fill_price) or fill_price <= 0:
            _reject_locked(row, funds, reason or "Invalid fill")
            return None, None
        fill_price = round(fill_price, 4)
        from backend.sandbox.brokerage import quote_charge, record_charge
        try:
            charge = quote_charge(db, user_id, fill_price, qty)
        except ValueError as error:
            _reject_locked(row, funds, str(error))
            return None, None
        fee = charge.fee_paise / 100 if charge else 0.0
        required = fund_manager.required_order_margin(db, user_id, row.symbol,
            row.exchange, row.product, row.action, qty, fill_price)
        reserved = row.margin_blocked if qty == remaining else round(row.margin_blocked * qty / remaining, 2)
        with db.begin_nested() as position_change:
            realized, released = apply_fill(user_id, row.symbol, row.exchange, row.product,
                row.action, qty, fill_price, required, db=db)
            cash = round(funds.available + reserved + released + realized - required - fee, 2)
            if required > 0 and cash < 0:
                position_change.rollback()
                _reject_locked(row, funds, "Insufficient sandbox funds for margin and brokerage at fill")
                return None, None
        funds.available = cash
        funds.used_margin = round(funds.used_margin + required - reserved - released, 2)
        funds.realized_pnl = round(funds.realized_pnl + realized - fee, 4)
        funds.today_realized_pnl = round(funds.today_realized_pnl + realized - fee, 4)
        funds.brokerage_paise += charge.fee_paise if charge else 0
        total = row.filled_quantity + qty
        row.average_price = round((row.average_price * row.filled_quantity + fill_price * qty) / total, 4)
        row.filled_quantity = total
        row.margin_blocked = round(row.margin_blocked - reserved, 2)
        row.status = "complete" if total == row.quantity else "open"
        trade = SandboxTrade(user_id=user_id, orderid=orderid, tradeid=new_tradeid(),
            symbol=row.symbol, exchange=row.exchange, action=row.action, quantity=qty,
            average_price=round(fill_price, 4), product=row.product, strategy=row.strategy)
        db.add(trade)
        trade.brokerage = record_charge(db, user_id, trade.tradeid, charge)
        db.flush()
        if owns_session:
            db.expunge(row)
            db.expunge(trade)
        return row, trade


def _reject_locked(row: SandboxOrder, funds, reason: str) -> None:
    released = min(row.margin_blocked, funds.used_margin)
    funds.used_margin = round(funds.used_margin - released, 2)
    funds.available = round(funds.available + released, 2)
    row.margin_blocked = 0.0
    row.status = "rejected"
    row.rejection_reason = reason[:500]


def reject_order(user_id: int, orderid: str, reason: str) -> None:
    with session_scope() as db:
        funds = fund_manager.ensure_fund_row(db, user_id)
        row = db.scalar(select(SandboxOrder).where(SandboxOrder.user_id == user_id,
            SandboxOrder.orderid == orderid).with_for_update())
        if row is not None and row.status in ("open", "trigger_pending"):
            _reject_locked(row, funds, reason)


def to_dict(order: SandboxOrder) -> dict[str, Any]:
    """Broker-compatible orderbook row shape.

    The ``timestamp`` field name matches what the live broker mappers
    (upstox, zerodha) produce — both map ``order_timestamp`` from the
    raw broker payload into ``timestamp`` so the React orderbook table
    can render either source. ``order_timestamp`` is kept as an alias
    to avoid breaking any internal sandbox code that still reads it.
    """
    ts = (
        order.order_timestamp.strftime("%d-%b-%Y %H:%M:%S")
        if isinstance(order.order_timestamp, datetime)
        else None
    )
    return {
        "orderid": order.orderid,
        "symbol": order.symbol,
        "exchange": order.exchange,
        "action": order.action,
        "order_status": order.status,
        "quantity": order.quantity,
        "filled_quantity": order.filled_quantity,
        "pending_quantity": max(0, order.quantity - order.filled_quantity),
        "pricetype": order.pricetype,
        "product": order.product,
        "price": round(order.price, 4),
        "trigger_price": round(order.trigger_price, 4),
        "average_price": round(order.average_price, 4),
        "timestamp": ts,
        "order_timestamp": ts,
        "strategy": order.strategy or "",
        "rejection_reason": order.rejection_reason or "",
    }


def trade_to_dict(trade: SandboxTrade) -> dict[str, Any]:
    """Tradebook row in the same shape live brokers' transform layers return.

    Field names + types match :func:`backend.broker.zerodha.mapping.order_data.transform_tradebook_data`
    (and the upstox equivalent), so the same React table renders both.
    Missing this contract — specifically the ``trade_value`` field — used to
    crash the TradeBook page with a ``toFixed`` of ``undefined`` error.
    """
    from backend.sandbox.brokerage import fee_fields
    qty = trade.quantity or 0
    avg = trade.average_price or 0.0
    ts = (
        trade.timestamp.strftime("%d-%b-%Y %H:%M:%S")
        if isinstance(trade.timestamp, datetime)
        else ""
    )
    return {
        **fee_fields(trade.brokerage),
        "tradeid": trade.tradeid,
        "orderid": trade.orderid,
        "symbol": trade.symbol,
        "exchange": trade.exchange,
        "action": trade.action,
        "product": trade.product,
        "quantity": int(qty),
        "average_price": round(float(avg), 4),
        "trade_value": trade.brokerage.notional_paise / 100 if trade.brokerage else round(float(qty) * float(avg), 2),
        "strategy": trade.strategy or "",
        "timestamp": ts,
        "trade_timestamp": ts,
    }


def fill_price_for(order, ltp: float) -> float | None:
    """Return the price this order should fill at given the current LTP,
    or ``None`` if the trigger condition is not met.

    Conventions (matching openalgo's sandbox):
      * MARKET  → fill at LTP immediately
      * LIMIT BUY  → fill when LTP <= limit price, execute at limit price
      * LIMIT SELL → fill when LTP >= limit price, execute at limit price
      * SL BUY   → trigger when LTP >= trigger_price, then behaves like a LIMIT BUY
      * SL SELL  → trigger when LTP <= trigger_price, then behaves like a LIMIT SELL
      * SL-M     → trigger + fill at LTP
    """
    if ltp <= 0:
        return None

    pt = order.pricetype.upper()
    action = order.action.upper()

    if pt == "MARKET":
        return ltp

    if pt == "LIMIT":
        if action == "BUY" and ltp <= order.price:
            return order.price
        if action == "SELL" and ltp >= order.price:
            return order.price
        return None

    if pt in ("SL", "SL-M"):
        # SL orders are trigger_pending until LTP crosses trigger.
        trigger = order.trigger_price
        triggered = (
            (action == "BUY" and ltp >= trigger) or
            (action == "SELL" and ltp <= trigger)
        )
        if not triggered:
            return None
        # Once triggered, SL fills at LIMIT price (if set), SL-M at LTP.
        if pt == "SL":
            if action == "BUY" and ltp <= order.price:
                return order.price
            if action == "SELL" and ltp >= order.price:
                return order.price
            return None
        return ltp  # SL-M

    return None

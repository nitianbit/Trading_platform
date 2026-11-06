"""Virtual cash and margin accounting. Mutations serialize on a PostgreSQL
transaction lock per account; used margin covers open positions and pending
orders. Trading commits order, fill, position and fund movements together.
"""

from __future__ import annotations

import logging

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.models.sandbox import SandboxFund
from backend.sandbox._db import session_scope
from backend.sandbox.config import get_leverage, get_leverage_for, get_starting_capital

logger = logging.getLogger(__name__)


def ensure_fund_row(db: Session, user_id: int) -> SandboxFund:
    # Transaction lock also serializes first-row creation across threads/processes.
    db.execute(select(func.pg_advisory_xact_lock(2082, user_id)))
    row = db.execute(
        select(SandboxFund).where(SandboxFund.user_id == user_id).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        capital = get_starting_capital(db)
        row = SandboxFund(
            user_id=user_id,
            starting_capital=capital,
            available=capital,
        )
        db.add(row)
        db.flush()
    return row


def compute_required_margin(
    db: Session,
    price: float,
    quantity: int,
    product: str,
    *,
    exchange: str = "",
    instrument_type: str = "",
    action: str = "",
) -> float:
    """Return margin required to hold this order open.

    When ``exchange``/``instrument_type``/``action`` are provided we use the
    instrument-aware leverage map (option BUY vs SELL, futures, equity MIS vs
    CNC). Without them we fall back to the legacy product-only map — kept so
    older callers (e.g. weekly_reset reconciling capital) keep working with
    no shape change.
    """
    if price <= 0 or quantity <= 0:
        return 0.0
    if exchange or instrument_type or action:
        leverage = get_leverage_for(
            exchange=exchange,
            product=product,
            instrument_type=instrument_type,
            action=action,
            db=db,
        )
    else:
        leverage = get_leverage(product, db)
    if leverage <= 0:
        leverage = 1.0
    return round((price * quantity) / leverage, 2)


def block_margin(user_id: int, amount: float) -> tuple[bool, str]:
    """Move ``amount`` from available → used. Fails if available is insufficient."""
    if amount <= 0:
        return True, ""
    with session_scope() as db:
        row = ensure_fund_row(db, user_id)
        if row.available < amount:
            return False, (
                f"Insufficient sandbox funds: required INR {amount:,.2f}, "
                f"available INR {row.available:,.2f}"
            )
        row.available -= amount
        row.used_margin += amount
    return True, ""


def release_margin(user_id: int, amount: float, realized_pnl: float = 0.0) -> None:
    """Move ``amount`` from used → available, optionally crediting realized PnL.

    Both mutations happen inside one transaction. Pass ``realized_pnl=0`` for a
    pure release (e.g. order cancel); pass a non-zero value when the release is
    triggered by a position reduce/close so the booked PnL hits the cash row in
    the same step the margin is freed.
    """
    if amount <= 0 and realized_pnl == 0:
        return
    with session_scope() as db:
        row = ensure_fund_row(db, user_id)
        if amount > 0:
            released = min(amount, row.used_margin)
            row.used_margin = round(row.used_margin - released, 2)
            row.available = round(row.available + released, 2)
        if realized_pnl != 0:
            row.available += realized_pnl
            row.realized_pnl += realized_pnl
            row.today_realized_pnl += realized_pnl


def transfer_margin_to_holdings(user_id: int, amount: float) -> None:
    """Reduce ``used_margin`` by ``amount`` without crediting *available*.

    Called when a long CNC position settles into holdings: the cash that was
    locked as margin is now embodied in the share itself, so the margin lock
    drops but no buying power is freed. Mirrors openalgo's
    ``transfer_margin_to_holdings`` behaviour (used_margin shrinks, asset
    value moves into the holdings book separately).
    """
    if amount <= 0:
        return
    with session_scope() as db:
        row = ensure_fund_row(db, user_id)
        row.used_margin = max(0.0, row.used_margin - amount)


def credit_sale_proceeds(user_id: int, amount: float) -> None:
    """Credit ``amount`` to ``available`` when settled holdings are sold.

    Mirrors openalgo's ``credit_sale_proceeds`` — sale proceeds flow back
    into buying power without touching the realized-PnL bucket (that's
    handled by ``release_margin``/``apply_realized_pnl`` for the trade)."""
    if amount <= 0:
        return
    with session_scope() as db:
        row = ensure_fund_row(db, user_id)
        row.available += amount


def apply_realized_pnl(user_id: int, amount: float) -> None:
    """Credit (+) / debit (-) realized PnL into ``available`` and the PnL buckets.

    Use :func:`release_margin` instead when realized PnL accompanies a margin
    release — it does both atomically in one transaction.
    """
    if amount == 0:
        return
    with session_scope() as db:
        row = ensure_fund_row(db, user_id)
        row.realized_pnl += amount
        row.today_realized_pnl += amount
        row.available += amount


def reset_today_realized_pnl(user_id: int) -> None:
    """Daily session boundary — clear today's realized PnL bucket. Cumulative
    ``realized_pnl`` is preserved."""
    with session_scope() as db:
        row = ensure_fund_row(db, user_id)
        row.today_realized_pnl = 0.0


def reset_funds(user_id: int) -> None:
    """Wipe PnL, reset available to starting_capital. Used by the weekly
    full-wipe and the per-user reset button."""
    with session_scope() as db:
        row = ensure_fund_row(db, user_id)
        capital = get_starting_capital(db)
        row.starting_capital = capital
        row.available = capital
        row.used_margin = 0.0
        row.realized_pnl = 0.0
        row.today_realized_pnl = 0.0
        row.unrealized_pnl = 0.0
        row.brokerage_paise = 0


def reconcile_margin(user_id: int, auto_fix: bool = True) -> tuple[bool, float, dict]:
    """Compare reserved margin with both open positions and pending orders.

    Positive drift may be released by an administrator; negative drift is
    reported without hiding an underfunded book.
    """
    from backend.models.sandbox import SandboxPosition, SandboxOrder

    with session_scope() as db:
        funds = ensure_fund_row(db, user_id)
        positions = (
            db.execute(
                select(SandboxPosition).where(
                    SandboxPosition.user_id == user_id,
                    SandboxPosition.net_quantity != 0,
                )
            )
            .scalars()
            .all()
        )
        position_total = round(
            sum(float(p.margin_blocked or 0.0) for p in positions), 2
        )
        order_total = round(sum(db.scalars(select(SandboxOrder.margin_blocked).where(
            SandboxOrder.user_id == user_id,
            SandboxOrder.status.in_(("open", "trigger_pending")),
        ))), 2)
        total = round(position_total + order_total, 2)
        used = round(float(funds.used_margin), 2)
        discrepancy = round(used - total, 2)
        details = {
            "user_id": user_id,
            "used_margin": used,
            "position_margin_total": position_total,
            "pending_order_margin_total": order_total,
            "discrepancy": discrepancy,
            "auto_fixed": False,
        }
        if discrepancy == 0:
            return True, 0.0, details
        if auto_fix and discrepancy > 0:
            funds.used_margin = total
            funds.available += discrepancy
            details["auto_fixed"] = True
            logger.warning(
                "sandbox: reconcile released INR %.2f stuck margin for user %d",
                discrepancy, user_id,
            )
            return True, 0.0, details
        return False, discrepancy, details


def get_funds_snapshot(user_id: int) -> dict:
    """Broker-compatible funds payload — shape matches Zerodha/Upstox mapping."""
    from backend.sandbox.position_manager import get_unrealized_total

    with session_scope() as db:
        row = ensure_fund_row(db, user_id)
        return {
            "availablecash": round(row.available, 2),
            "utiliseddebits": round(row.used_margin, 2),
            "collateral": 0.0,
            "m2munrealized": get_unrealized_total(db, user_id),
            "m2mrealized": round(row.realized_pnl, 2),
            "brokerage_paid": row.brokerage_paise / 100,
            "gross_realized_pnl": round(row.realized_pnl + row.brokerage_paise / 100, 2),
        }


def required_order_margin(db: Session, user_id: int, symbol: str, exchange: str,
                          product: str, action: str, quantity: int, price: float) -> float:
    from backend.models.sandbox import SandboxPosition
    from backend.sandbox.symbol_info import get_symbol_info
    position = db.scalar(select(SandboxPosition).where(
        SandboxPosition.user_id == user_id, SandboxPosition.symbol == symbol,
        SandboxPosition.exchange == exchange, SandboxPosition.product == product,
    ))
    net = position.net_quantity if position is not None else 0
    signed = quantity if action == "BUY" else -quantity
    opening = quantity if net * signed >= 0 else max(0, quantity - abs(net))
    info = get_symbol_info(symbol, exchange, db=db)
    return compute_required_margin(db, price, opening, product, exchange=exchange,
        instrument_type=info.instrument_type if info else "", action=action)

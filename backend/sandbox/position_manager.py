"""Position accounting shared by transactional fills and startup settlement.

The order ledger supplies margin for fresh exposure at fill time and owns
cash movement. Mark-to-market uses the same account lock as fills.
"""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text, func
from sqlalchemy.orm import Session

from backend.models.sandbox import SandboxPosition, SandboxTrade
from backend.sandbox._db import session_scope

logger = logging.getLogger(__name__)

# IST is fixed UTC+05:30 — same convention as catch_up.py / scheduler.py.
_IST = timezone(timedelta(hours=5, minutes=30))


def _last_session_boundary() -> datetime:
    """Return the most recent session boundary (00:00 IST today, or yesterday
    if it's still before midnight IST)."""
    now = datetime.now(tz=_IST)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _get_or_create(
    db: Session, user_id: int, symbol: str, exchange: str, product: str
) -> SandboxPosition:
    row = db.execute(
        select(SandboxPosition).where(
            SandboxPosition.user_id == user_id,
            SandboxPosition.symbol == symbol,
            SandboxPosition.exchange == exchange,
            SandboxPosition.product == product,
        )
    ).scalar_one_or_none()
    if row is None:
        row = SandboxPosition(
            user_id=user_id, symbol=symbol, exchange=exchange, product=product
        )
        db.add(row)
        db.flush()
    return row


def get_position_snapshot(
    user_id: int, symbol: str, exchange: str, product: str
) -> tuple[int, float] | None:
    """Read-only snapshot used by ``place_order`` for position-aware margin
    sizing. Returns ``(net_quantity, margin_blocked)`` or ``None`` if the
    position doesn't exist / is flat."""
    with session_scope() as db:
        row = db.execute(
            select(SandboxPosition.net_quantity, SandboxPosition.margin_blocked).where(
                SandboxPosition.user_id == user_id,
                SandboxPosition.symbol == symbol,
                SandboxPosition.exchange == exchange,
                SandboxPosition.product == product,
            )
        ).first()
        if row is None or int(row[0]) == 0:
            return None
        return int(row[0]), float(row[1] or 0.0)


def apply_fill(
    user_id: int,
    symbol: str,
    exchange: str,
    product: str,
    action: str,
    quantity: int,
    price: float,
    order_margin: float = 0.0,
    *, db: Session | None = None,
) -> tuple[float, float]:
    """Update the position for a single fill.

    Returns ``(realized_pnl, margin_to_release)``:
      * ``realized_pnl`` — PnL booked on the offset portion of this fill (0
        for new / accumulating positions).
      * ``margin_to_release`` — margin that must be released from
        ``used_margin`` back to *available*. The caller pairs this with the
        realized PnL in a single :func:`fund_manager.release_margin` call so
        cash and PnL move together.

    For the same-direction (new / accumulate) path, the order's margin is
    moved from the order row into the position row inside this function — the
    return tuple is ``(0, 0)`` because nothing leaves *used_margin*.
    """
    action = action.upper()
    signed_qty = quantity if action == "BUY" else -quantity

    realized_delta = 0.0
    margin_to_release = 0.0

    with (nullcontext(db) if db is not None else session_scope()) as db:
        pos = _get_or_create(db, user_id, symbol, exchange, product)
        old_net = pos.net_quantity
        old_avg = pos.average_price
        old_margin = float(pos.margin_blocked or 0.0)

        # ---------------------------------------------------------------
        # Same direction (or fresh position) — accumulate, transfer margin
        # ---------------------------------------------------------------
        if (old_net >= 0 and signed_qty > 0) or (old_net <= 0 and signed_qty < 0):
            new_net = old_net + signed_qty
            new_total_cost = old_avg * abs(old_net) + price * abs(signed_qty)
            new_avg = new_total_cost / abs(new_net) if new_net != 0 else 0.0
            pos.net_quantity = new_net
            # Preserve weighted cost internally; four decimals are an output format.
            pos.average_price = new_avg
            # Transfer the order's blocked margin onto the position. No fund
            # movement — `used_margin` already reflects this amount; only its
            # bookkeeping bucket (order → position) changes.
            pos.margin_blocked = round(old_margin + float(order_margin or 0.0), 2)

        # ---------------------------------------------------------------
        # Opposite direction — realize PnL, release margin pro-rata
        # ---------------------------------------------------------------
        else:
            offset_qty = min(abs(old_net), abs(signed_qty))
            previous_realized = Decimal(str(pos.realized_pnl or 0.0))
            gross = (Decimal(str(price)) - Decimal(str(old_avg))) * offset_qty
            if old_net < 0:
                gross = -gross
            cumulative_realized = previous_realized + gross
            # Post the change in rounded cumulative money, carrying sub-paise
            # residuals in the position rather than creating cash on each close.
            paise = Decimal("0.01")
            realized_delta = float(cumulative_realized.quantize(paise, rounding=ROUND_HALF_UP)
                - previous_realized.quantize(paise, rounding=ROUND_HALF_UP))

            remaining = abs(signed_qty) - offset_qty
            new_net = old_net + signed_qty

            # Pro-rata margin release for the offset portion.
            if abs(old_net) > 0 and old_margin > 0:
                proportion = offset_qty / float(abs(old_net))
                margin_to_release = round(old_margin * proportion, 2)
            else:
                margin_to_release = 0.0

            pos.net_quantity = new_net
            if new_net == 0:
                # Fully closed — drop average + clear the rest of the margin
                # in case rounding left a sliver behind.
                pos.average_price = 0.0
                margin_to_release = round(old_margin, 2)
                pos.margin_blocked = 0.0
            elif remaining > 0:
                # Reversed direction with leftover — the new (opposite-side)
                # position is opened at ``price``. The order was sized to
                # block margin only for the leftover (see ``place_order``
                # position-aware logic), so order_margin == margin for the
                # new residual position.
                pos.average_price = round(price, 4)
                # Old position is fully closed → release ALL of its margin.
                margin_to_release = round(old_margin, 2)
                pos.margin_blocked = round(float(order_margin or 0.0), 2)
            else:
                # Reduced but not closed — keep the residual margin on the
                # position (= old_margin minus what we released).
                pos.margin_blocked = round(max(0.0, old_margin - margin_to_release), 2)
                # average_price unchanged

            pos.realized_pnl = float(cumulative_realized)
            pos.today_realized_pnl = round(
                float(pos.today_realized_pnl or 0.0) + realized_delta, 4
            )

        # ---------------------------------------------------------------
        # Intraday + display fields
        # ---------------------------------------------------------------
        if action == "BUY":
            pos.day_buy_quantity += quantity
            pos.day_buy_value = round(pos.day_buy_value + price * quantity, 2)
        else:
            pos.day_sell_quantity += quantity
            pos.day_sell_value = round(pos.day_sell_value + price * quantity, 2)

        # Each fill changes quantity/cost; refresh the position-owned values now.
        pos.ltp = round(price, 4)
        pos.unrealized_pnl = round((price - pos.average_price) * pos.net_quantity, 4)
        pos.pnl = round(pos.realized_pnl + pos.unrealized_pnl, 4)

    return round(realized_delta, 4), round(margin_to_release, 2)


def mark_to_market(
    user_id: int, symbol: str, exchange: str, product: str, ltp: float
) -> None:
    """Refresh ``ltp`` and unrealized PnL for a single position."""
    if ltp <= 0:
        return
    with session_scope() as db:
        from backend.sandbox.fund_manager import ensure_fund_row
        ensure_fund_row(db, user_id)
        pos = db.execute(
            select(SandboxPosition).where(
                SandboxPosition.user_id == user_id,
                SandboxPosition.symbol == symbol,
                SandboxPosition.exchange == exchange,
                SandboxPosition.product == product,
            )
        ).scalar_one_or_none()
        if pos is None or pos.net_quantity == 0:
            return
        pos.ltp = round(ltp, 4)
        # Long: (ltp - avg) * qty. Short: (avg - ltp) * qty.
        if pos.net_quantity > 0:
            pos.unrealized_pnl = round((ltp - pos.average_price) * pos.net_quantity, 4)
        else:
            pos.unrealized_pnl = round((pos.average_price - ltp) * abs(pos.net_quantity), 4)
        pos.pnl = round(pos.realized_pnl + pos.unrealized_pnl, 4)


def get_positions(user_id: int) -> list[dict]:
    """Broker-compatible position payload — shape matches the transform layer.

    Applies a
    session-aware filter so closed positions from previous sessions don't
    linger on the page (mirrors openalgo's ``get_open_positions``):

      * ``net_quantity != 0``                              → show open position
      * ``net_quantity == 0`` and a SandboxTrade exists for
        (symbol, exchange, product) since the session boundary
                                                           → show today's flatten
      * ``net_quantity != 0`` and product == "NRML" and
        updated last session                                → carry-forward
      * everything else                                     → hide

    Source of truth for "traded today" is the SandboxTrade table — not
    ``today_realized_pnl`` or ``updated_at`` on SandboxPosition. Those two
    are easy to corrupt: ``daily_reset.reset_today_pnl()`` issues a Core
    UPDATE which fires the ``onupdate=func.now()`` column default, bumping
    ``updated_at`` to today even though no real activity happened. Trading
    history doesn't have that problem — a trade row is permanent.

    Read-side heal: any qty=0 position with non-zero ``today_realized_pnl``
    that didn't trade this session has the bucket zeroed via raw SQL (so
    ``updated_at`` stays put for diagnostics).
    """
    boundary = _last_session_boundary()

    with session_scope() as db:
        # 1. The set of (symbol, exchange, product) tuples that actually
        #    fired a fill since the session boundary. SandboxTrade rows are
        #    immutable — perfect ground truth.
        traded_rows = db.execute(
            select(
                SandboxTrade.symbol,
                SandboxTrade.exchange,
                SandboxTrade.product,
            )
            .where(SandboxTrade.user_id == user_id)
            .where(SandboxTrade.timestamp >= boundary)
            .distinct()
        ).all()
        traded_today: set[tuple[str, str, str]] = {
            (sym, exch, prod) for sym, exch, prod in traded_rows
        }

        rows = db.execute(
            select(SandboxPosition).where(SandboxPosition.user_id == user_id)
        ).scalars().all()

        # 2. Heal stale today_realized_pnl on qty=0 rows that didn't trade
        #    this session. Raw SQL so the heal itself doesn't bump
        #    updated_at and confuse downstream tooling.
        ids_to_heal = [
            r.id
            for r in rows
            if r.net_quantity == 0
            and float(r.today_realized_pnl or 0.0) != 0.0
            and (r.symbol, r.exchange, r.product) not in traded_today
        ]
        if ids_to_heal:
            from sqlalchemy import bindparam

            db.execute(
                text(
                    "UPDATE sandbox_positions SET today_realized_pnl = 0 "
                    "WHERE id IN :ids"
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": ids_to_heal},
            )
            heal_set = set(ids_to_heal)
            for r in rows:
                if r.id in heal_set:
                    r.today_realized_pnl = 0.0
            logger.info(
                "get_positions: zeroed stale today_realized_pnl on %d row(s)",
                len(ids_to_heal),
            )

        # 3. Filter rows by trade activity (qty=0 only shows when traded
        #    today) plus NRML carry-forward.
        visible: list[SandboxPosition] = []
        for r in rows:
            if r.net_quantity != 0:
                # Open position — always show. NRML carry-forward also
                # lands here (qty != 0, updated_at < boundary).
                visible.append(r)
                continue
            # qty == 0 — only show if there was a real trade this session.
            if (r.symbol, r.exchange, r.product) in traded_today:
                visible.append(r)

        return [
            {
                "symbol": r.symbol,
                "exchange": r.exchange,
                "product": r.product,
                "quantity": r.net_quantity,
                "netqty": r.net_quantity,
                "buyqty": r.day_buy_quantity,
                "sellqty": r.day_sell_quantity,
                # Closed positions (qty=0) display avg=0 / pnlpercent=0 the
                # way Zerodha + openalgo do — the cumulative realized_pnl
                # field still carries the historical number for callers
                # that care.
                "average_price": (
                    round(r.average_price, 4) if r.net_quantity != 0 else 0.0
                ),
                "averageprice": (
                    round(r.average_price, 4) if r.net_quantity != 0 else 0.0
                ),
                "ltp": round(r.ltp, 4),
                "pnl": round(
                    r.pnl if r.net_quantity != 0
                    else float(r.today_realized_pnl or 0.0),
                    2,
                ),
                "unrealized_pnl": round(r.unrealized_pnl, 2),
                "realized_pnl": round(r.realized_pnl, 2),
                "today_realized_pnl": round(float(r.today_realized_pnl or 0.0), 2),
                "margin_blocked": round(float(r.margin_blocked or 0.0), 2),
            }
            for r in visible
        ]


def get_unrealized_total(db: Session, user_id: int) -> float:
    """Derive the account total from its open positions, including the empty book."""
    value = db.scalar(select(func.coalesce(func.sum(SandboxPosition.unrealized_pnl), 0)).where(
        SandboxPosition.user_id == user_id, SandboxPosition.net_quantity != 0,
    ))
    return round(float(value), 2)

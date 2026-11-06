"""
Weekly wipe of sandbox state.

If ``sandbox_config.reset_day`` is ``"Never"`` this is disabled. Otherwise on
the explicitly configured day at ``reset_time`` IST we reset
every user's sandbox to the current ``starting_capital`` — orders, trades,
positions, holdings, daily P&L are all deleted, funds restored.

This is deliberately *per-user* rather than dropping tables: the starting
capital applied to each user is whatever the global config says at the
moment of reset.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, select

from backend.models.sandbox import (
    SandboxDailyPnL,
    SandboxFund,
    SandboxHolding,
    SandboxOrder,
    SandboxPosition,
    SandboxTrade,
)
from backend.sandbox._db import session_scope
from backend.sandbox import fund_manager

logger = logging.getLogger(__name__)


def reset_user(user_id: int) -> None:
    """Reset one account atomically with the same lock used for trading."""
    from backend.sandbox.config import get_starting_capital
    with session_scope() as db:
        funds = fund_manager.ensure_fund_row(db, user_id)
        for model in (SandboxOrder, SandboxTrade, SandboxPosition, SandboxHolding, SandboxDailyPnL):
            db.execute(delete(model).where(model.user_id == user_id))
        capital = get_starting_capital(db)
        funds.starting_capital = capital
        funds.available = capital
        funds.used_margin = 0.0
        funds.realized_pnl = 0.0
        funds.today_realized_pnl = 0.0
        funds.unrealized_pnl = 0.0
        funds.brokerage_paise = 0


def wipe_all_users() -> int:
    users = set()
    with session_scope() as db:
        for model in (SandboxFund, SandboxOrder, SandboxTrade, SandboxPosition, SandboxHolding):
            users.update(db.scalars(select(model.user_id).distinct()))
    for user_id in sorted(users):
        reset_user(user_id)
    return len(users)

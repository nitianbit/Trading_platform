"""Refresh position-owned LTP and unrealized P&L. Account totals derive on read."""

from __future__ import annotations

import logging
import threading
from typing import Optional

from sqlalchemy import select

from backend.models.sandbox import SandboxPosition
from backend.sandbox._db import session_scope
from backend.sandbox.config import get_mtm_update_interval

logger = logging.getLogger(__name__)


_running = False
_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_lock = threading.Lock()


def _refresh_once() -> int:
    """Refresh open positions, preserving their prior values when no quote exists."""
    from backend.sandbox.quote_helper import get_ltp as get_ltp_with_fallback

    from backend.sandbox.position_manager import mark_to_market
    with session_scope() as db:
        rows = db.execute(select(SandboxPosition.user_id, SandboxPosition.symbol,
            SandboxPosition.exchange, SandboxPosition.product).where(SandboxPosition.net_quantity != 0)).all()
    touched = 0
    for uid, symbol, exchange, product in rows:
        ltp = get_ltp_with_fallback(uid, symbol, exchange)
        if ltp is not None and ltp > 0:
            mark_to_market(uid, symbol, exchange, product, ltp)
            touched += 1
    return touched


def _loop() -> None:
    while not _stop_event.is_set():
        try:
            interval = max(1, get_mtm_update_interval())
        except Exception:
            interval = 5
        try:
            _refresh_once()
        except Exception:
            logger.exception("mtm: refresh pass raised")
        _stop_event.wait(interval)


def start() -> None:
    """Launch the MTM daemon. Idempotent."""
    global _running, _thread
    with _lock:
        if _running:
            return
        _running = True
        _stop_event.clear()
        _thread = threading.Thread(target=_loop, name="sandbox-mtm", daemon=True)
        _thread.start()
        logger.info("sandbox MTM updater started")


def stop(timeout: float = 2.0) -> None:
    global _running, _thread
    with _lock:
        if not _running:
            return
        _running = False
        _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=timeout)
    _thread = None

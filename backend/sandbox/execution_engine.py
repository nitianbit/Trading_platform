"""
Sandbox execution engine.

Two paths fill pending orders:

1. **Tick-driven** — a CRITICAL-priority subscriber on the shared
   :class:`MarketDataCache` receives every authenticated broker tick. For the
   symbol in that tick we iterate pending orders and fill any whose trigger
   condition is met.
2. **Polling fallback** — every 5 s (configurable) we scan all pending orders
   and try to fill them using whatever LTP the cache currently holds. This
   keeps LIMIT / SL orders progressing when the broker feed goes quiet.

Both paths call the same :func:`_try_fill_order` — one code path, two triggers.
Safe under thread concurrency because order_manager / position_manager /
fund_manager each open their own scoped session; each fill mutation is atomic.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from backend.sandbox import order_manager, position_manager, fund_manager
from backend.sandbox.config import get_order_check_interval

logger = logging.getLogger(__name__)


# -- global state ---------------------------------------------------------

_running = False
_subscriber_id: int | None = None
_poll_thread: threading.Thread | None = None
_stop_event = threading.Event()
_lock = threading.Lock()


# -- fill decision --------------------------------------------------------


def _try_fill_order(order, ltp: float) -> bool:
    row, trade = order_manager.fill(order.user_id, order.orderid, ltp, ltp=ltp)
    return row is not None and trade is not None


# -- tick callback --------------------------------------------------------

def _on_tick(data: dict[str, Any]) -> None:
    """MarketDataCache CRITICAL subscriber. Runs on the broker tick thread."""
    try:
        symbol = data.get("symbol")
        exchange = data.get("exchange")
        payload = data.get("data") or {}
        ltp_val = payload.get("ltp")
        if not symbol or not exchange or not isinstance(ltp_val, (int, float)) or ltp_val <= 0:
            return

        # Pull only pending orders for this symbol. list_pending_orders returns
        # everything across users; we filter in memory — cheap because the set
        # of pending orders is small (seconds to minutes lifetime).
        for order in order_manager.list_pending_orders():
            if order.symbol != symbol or order.exchange != exchange:
                continue
            _try_fill_order(order, float(ltp_val))
    except Exception:
        logger.exception("sandbox tick handler failed")


# -- polling fallback -----------------------------------------------------

def _poll_loop() -> None:
    """Fallback poll loop. Tries cached LTP first; falls back to a broker
    quote keyed off the order's user. Without the broker fallback, MARKET
    orders placed after market hours (when no tick stream is running) would
    sit at ``open`` forever — same bug openalgo solved with its multiquotes
    fallback in the execution engine."""
    from backend.sandbox.quote_helper import get_ltp as get_ltp_with_fallback

    while not _stop_event.is_set():
        try:
            interval = max(1, get_order_check_interval())
        except Exception:
            interval = 5
        try:
            pending = order_manager.list_pending_orders()
            for order in pending:
                ltp = get_ltp_with_fallback(order.user_id, order.symbol, order.exchange)
                if ltp is None or ltp <= 0:
                    continue
                _try_fill_order(order, float(ltp))
        except Exception:
            logger.exception("sandbox poll iteration failed")
        _stop_event.wait(interval)


# -- lifecycle ------------------------------------------------------------

def start() -> None:
    """Call once at app startup. Idempotent."""
    global _running, _subscriber_id, _poll_thread
    with _lock:
        if _running:
            return
        _running = True
        _stop_event.clear()

        # Tick-driven path
        try:
            from backend.services.market_data_cache import (
                get_market_data_cache,
                SubscriberPriority,
            )

            mds = get_market_data_cache()
            _subscriber_id = mds.subscribe(
                priority=SubscriberPriority.CRITICAL,
                event_type="all",
                callback=_on_tick,
                filter_symbols=None,
                name="sandbox_execution_engine",
            )
            logger.info("sandbox execution engine subscribed (id=%s)", _subscriber_id)
        except Exception:
            logger.exception("sandbox: MDS subscribe failed — relying on polling only")

        # Polling fallback
        _poll_thread = threading.Thread(
            target=_poll_loop, name="sandbox-exec-poll", daemon=True
        )
        _poll_thread.start()


def stop() -> None:
    global _running, _subscriber_id, _poll_thread
    with _lock:
        if not _running:
            return
        _running = False
        _stop_event.set()

    # Unsubscribe (best-effort)
    try:
        from backend.services.market_data_cache import get_market_data_cache

        if _subscriber_id is not None:
            get_market_data_cache().unsubscribe(_subscriber_id)
    except Exception:
        pass
    _subscriber_id = None

    if _poll_thread is not None:
        _poll_thread.join(timeout=2.0)
    _poll_thread = None

"""Synthetic demonstration instruments. These are not exchange quotes/contracts."""
import asyncio
import calendar
import math
import logging
import time
from datetime import date, timedelta

logger = logging.getLogger(__name__)
_last_success = 0.0
_seeded_day = None

from sqlalchemy import select
from backend.models.symbol import SymToken
from backend.sandbox._db import session_scope
from backend.services.market_data_cache import get_market_data_cache

from backend.paper.catalog import INSTRUMENTS, BY_KEY


def quote_at(row: dict, timestamp: float) -> dict:
    phase = INSTRUMENTS.index(row) * 0.9
    slot = int(timestamp // 2) * 2
    movement = 0.0025 * math.sin(slot / 47 + phase) + 0.001 * math.sin(slot / 13 + phase)
    price = round(round(row["base"] * (1 + movement) / row["tick"]) * row["tick"], 4)
    change = round(price - row["base"], 2)
    return {
        "ltp": price, "open": row["base"], "close": row["base"],
        "high": max(price, round(row["base"] * 1.004, 2)),
        "low": min(price, round(row["base"] * 0.996, 2)),
        "prev_close": row["base"], "change": change,
        "change_percent": round(change / row["base"] * 100, 2),
        "volume": 10000, "oi": 50000, "timestamp": slot,
        "bid": round(price - row["tick"], 4), "ask": round(price + row["tick"], 4),
        "data_source": "synthetic_demo",
    }


def get_quote(symbol: str, exchange: str) -> dict:
    row = BY_KEY.get((symbol, exchange))
    if row is None:
        raise ValueError("This instrument is unavailable in the demonstration feed.")
    return quote_at(row, time.time())


def seed_symbols() -> None:
    global _seeded_day
    today = date.today()
    month_end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    expiry = (month_end + timedelta(days=28)).isoformat()
    with session_scope() as db:
        for index, row in enumerate(INSTRUMENTS):
            existing = db.execute(select(SymToken).where(
                SymToken.symbol == row["symbol"], SymToken.exchange == row["exchange"]
            )).scalar_one_or_none()
            if existing is not None:
                existing.expiry = expiry if row["kind"] != "EQ" else None
            else:
                db.add(SymToken(
                    symbol=row["symbol"], brsymbol=row["symbol"], name=row["name"],
                    exchange=row["exchange"], brexchange=row["exchange"],
                    token=f"DEMO-{index}", expiry=expiry if row["kind"] != "EQ" else None, strike=row.get("strike", 0),
                    lotsize=row["lot"], instrumenttype=row["kind"], tick_size=row["tick"],
                ))
    _seeded_day = today


def publish_quotes() -> None:
    global _last_success
    if _seeded_day != date.today():
        seed_symbols()
    cache = get_market_data_cache()
    for row in INSTRUMENTS:
        data = get_quote(row["symbol"], row["exchange"])
        for mode in (2, 1):
            cache.process_market_data({
                "symbol": row["symbol"], "exchange": row["exchange"], "mode": mode, "data": data,
            })
    _last_success = time.monotonic()


def feed_is_healthy() -> bool:
    return _last_success > 0 and time.monotonic() - _last_success < 15


async def _run_demo_feed() -> None:
    while True:
        try:
            await asyncio.to_thread(publish_quotes)
        except Exception:
            logger.exception("Synthetic feed publication failed; fills pause on stale quotes")
        await asyncio.sleep(2)


async def run_feed() -> None:
    from backend.paper.public_prices import run_public_feed
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(_run_demo_feed())
        tasks.create_task(run_public_feed())

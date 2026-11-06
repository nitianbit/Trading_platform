"""Shared, read-only free public quotes. Never used to price exchange orders."""
import asyncio
from datetime import datetime
import logging
import math
from threading import Lock
import time

import httpx
from backend.paper.catalog import REFERENCE_ASSETS
from backend.paper.policy import read_policy

logger = logging.getLogger(__name__)
_quotes: dict[str, dict] = {}
_lock = Lock()
MAX_AGE = 90


def parse_quote(payload: object, symbol: str, now: float) -> dict:
    if not isinstance(payload, dict) or payload.get("symbol") != symbol or payload.get("currency") != "USD":
        raise ValueError("Unexpected quote identity or currency")
    price = payload.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        raise ValueError("Invalid quote price")
    raw = payload.get("updatedAt")
    if not isinstance(raw, str):
        raise ValueError("Missing provider timestamp")
    updated = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if updated.tzinfo is None or updated.utcoffset().total_seconds() != 0:
        raise ValueError("Expected UTC provider timestamp")
    timestamp = updated.timestamp()
    if timestamp > now + 30:
        raise ValueError("Provider timestamp is in the future")
    return dict(price=float(price), updated_at=updated.isoformat(), timestamp=timestamp, received_at=now, error=False)


def snapshot(policy, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    rows = []
    with _lock:
        quotes = {key: value.copy() for key, value in _quotes.items()}
    for asset in REFERENCE_ASSETS:
        if asset["symbol"] in policy.disabled_reference_assets:
            continue
        quote = quotes.get(asset["symbol"], {})
        if not policy.public_feed_enabled:
            status = "disabled"
        elif not quote or quote.get("error"):
            status = "unavailable"
        elif now - quote["timestamp"] > MAX_AGE or now - quote["received_at"] > MAX_AGE:
            status = "stale"
        else:
            status = "live"
        rows.append({**asset, "price": quote.get("price") if status == "live" else None,
            "updated_at": quote.get("updated_at"), "status": status, "currency": "USD"})
    return dict(provider="gold-api.com", source_url="https://gold-api.com/", enabled=policy.public_feed_enabled,
        refresh_seconds=30, reference_only=True, assets=rows)


async def run_public_feed() -> None:
    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        while True:
            try:
                policy = await asyncio.to_thread(read_policy)
                if policy.public_feed_enabled:
                    for asset in REFERENCE_ASSETS:
                        symbol = asset["symbol"]
                        if symbol in policy.disabled_reference_assets:
                            continue
                        try:
                            response = await client.get(f"https://api.gold-api.com/price/{symbol}")
                            response.raise_for_status()
                            quote = parse_quote(response.json(), symbol, time.time())
                            with _lock:
                                recovered = _quotes.get(symbol, {}).get("error", False)
                                _quotes[symbol] = quote
                            if recovered:
                                logger.info("Public reference quote recovered: %s", symbol)
                        except (httpx.HTTPError, ValueError, TypeError, OverflowError):
                            with _lock:
                                first_failure = not _quotes.get(symbol, {}).get("error", False)
                                _quotes.setdefault(symbol, {})["error"] = True
                            if first_failure:
                                logger.warning("Public reference quote unavailable: %s; further failures suppressed until recovery", symbol)
                        # Provider requests at most one request per second, with a 30-second cache.
                        await asyncio.sleep(1.1)
            except Exception:
                logger.exception("Public reference feed could not read platform policy")
            await asyncio.sleep(30)

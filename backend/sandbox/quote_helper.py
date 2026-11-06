"""Only fresh platform feed ticks may price paper execution."""
from backend.services.market_data_cache import get_market_data_cache


def get_ltp(user_id: int, symbol: str, exchange: str) -> float | None:
    cache = get_market_data_cache()
    if not cache.is_data_fresh(symbol, exchange, max_age_seconds=15):
        return None
    value = cache.get_ltp_value(symbol, exchange)
    return float(value) if value is not None and value > 0 else None

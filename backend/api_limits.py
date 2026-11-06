"""Shared asynchronous admission limits for authentication and trading APIs."""
from fastapi import HTTPException, Request
from limits import parse
from sqlalchemy.engine import make_url
from limits.aio.storage import RedisStorage
from limits.aio.strategies import MovingWindowRateLimiter
from backend.config import get_settings

settings = get_settings()
storage = RedisStorage(settings.redis_url, implementation="redispy", key_prefix="DHK_LIMITS:" + str(make_url(settings.database_url).database), socket_connect_timeout=2, socket_timeout=2)
rate_limiter = MovingWindowRateLimiter(storage)
ORDER_ENDPOINTS = {"placeorder", "placesmartorder", "modifyorder", "cancelorder", "cancelallorder", "closeposition", "basketorder", "splitorder", "multilegorder"}


async def admit(rule: str, *keys: str) -> None:
    try:
        allowed = await rate_limiter.hit(parse(rule), *keys)
    except Exception:
        raise HTTPException(503, "Rate limiter unavailable") from None
    if not allowed:
        raise HTTPException(429, "Too many requests; try again shortly", headers={"Retry-After": "1"})


async def check_api_rate(request: Request, user_id: int | None = None) -> None:
    if user_id is None:
        await admit(settings.api_rate_limit, "api", request.client.host if request.client else "unknown")
    elif request.url.path.rsplit("/", 1)[-1] in ORDER_ENDPOINTS:
        await admit(settings.order_rate_limit, "orders", str(user_id))


async def check_login_rate(request: Request, username: str) -> None:
    address = request.client.host if request.client else "unknown"
    await admit("60 per minute", "login-ip", address)
    for rule in (settings.login_rate_limit_min, settings.login_rate_limit_hour):
        await admit(rule, "login", address, username.strip().lower())

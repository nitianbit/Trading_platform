import logging
from typing import AsyncGenerator

from fastapi import Request, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session
from backend.models.user import User
from backend.models.auth import ApiKey
from backend.models.audit import ActiveSession
from backend.security import decode_access_token, hash_api_key
from backend.utils.redis_client import (
    cache_delete,
    cache_delete_pattern,
    cache_get_json,
    cache_set_json,
)

logger = logging.getLogger(__name__)

def _key_broker_ctx(user_id: int) -> str:
    return f"broker_ctx:{user_id}"


def _key_api_ctx(user_id: int) -> str:
    return f"api_ctx:{user_id}"


async def invalidate_all_caches() -> None:
    """Clear all API key / broker context caches. Called on API key rotation or logout."""
    await cache_delete_pattern("api_key:*")
    await cache_delete_pattern("broker_ctx:*")
    await cache_delete_pattern("api_ctx:*")


async def invalidate_user_cache(user_id: int) -> None:
    """Clear cached broker context for a single user. Call on logout / re-auth."""
    await cache_delete(_key_broker_ctx(user_id), _key_api_ctx(user_id))


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    # Enforce server-side session revocation: the JWT's jti must match a
    # live ActiveSession row for this user. Logout (and "log out all
    # devices") deletes those rows, invalidating any outstanding cookies
    # even though the JWT itself is still cryptographically valid.
    jti = payload.get("jti")
    if not jti:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    session_result = await db.execute(
        select(ActiveSession).where(
            ActiveSession.user_id == int(user_id),
            ActiveSession.session_token == jti,
        )
    )
    if session_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=401, detail="Session revoked")

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    from backend.paper.hierarchy import account_can_access
    if not await account_can_access(db, user):
        raise HTTPException(status_code=401, detail="Account or broker access is disabled")

    # Attach broker info from JWT to user object for convenience
    user._broker = payload.get("broker")
    user._session_token = jti
    # Tell ApiLogMiddleware this request is authenticated — without this tag,
    # the middleware skips the row so unauthenticated noise never hits the DB.
    request.state.user_id = user.id
    request.state.auth_method = "session"
    return user


class BrokerContext:
    def __init__(self, user: User, auth_token: str, broker_name: str, broker_config: dict):
        self.user = user
        self.auth_token = auth_token
        self.broker_name = broker_name
        self.broker_config = broker_config


async def get_broker_context(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerContext:
    return BrokerContext(user=user, auth_token="paper", broker_name="demo", broker_config={})


async def get_api_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> tuple[int, str, str, dict]:
    """Resolve API key to (user_id, auth_token, broker_name, broker_config).
    Used by external /api/v1/* endpoints.
    """
    from backend.api_limits import check_api_rate
    await check_api_rate(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    provided_key = (body.get("apikey") if isinstance(body, dict) else None) or request.headers.get("X-API-KEY")
    if not isinstance(provided_key, str) or not 1 <= len(provided_key) <= 256:
        raise HTTPException(status_code=401, detail="Valid API key required")
    user_id = await db.scalar(select(ApiKey.user_id).where(ApiKey.api_key_hash == hash_api_key(provided_key)))
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    from backend.paper.hierarchy import account_can_access
    if not await account_can_access(db, await db.get(User, user_id)):
        raise HTTPException(status_code=401, detail="Account or broker access is disabled")
    await check_api_rate(request, user_id)
    request.state.user_id = user_id
    request.state.auth_method = "api_key"
    return (user_id, "paper", "demo", {})

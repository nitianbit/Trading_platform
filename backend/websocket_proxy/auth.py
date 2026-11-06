"""Indexed platform API-key verification for the read-only paper quote proxy."""
from sqlalchemy import select
from backend.database import async_session
from backend.models.auth import ApiKey
from backend.models.user import User
from backend.paper.hierarchy import account_can_access
from backend.security import hash_api_key


async def verify_api_key_standalone(api_key: str) -> tuple[int, str, str, dict]:
    if not isinstance(api_key, str) or not 1 <= len(api_key) <= 256:
        raise ValueError("Invalid API key")
    async with async_session() as db:
        uid = await db.scalar(select(ApiKey.user_id).where(ApiKey.api_key_hash == hash_api_key(api_key)))
        if uid is None or not await account_can_access(db, await db.get(User, uid)):
            raise ValueError("Invalid API key or disabled account")
        return uid, "paper", "demo", {}

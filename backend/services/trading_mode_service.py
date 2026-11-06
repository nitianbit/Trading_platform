"""DHK Paper has one execution mode, independent of database/cache state."""
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


def get_trading_mode_sync() -> str:
    return "sandbox"


async def get_trading_mode(db: AsyncSession | None = None) -> str:
    return "sandbox"


async def set_trading_mode(db: AsyncSession, mode: str) -> str:
    if mode != "sandbox":
        raise ValueError("DHK Paper supports paper trading only. Live execution is unavailable.")
    return "sandbox"


def invalidate_cache() -> None:
    pass


def is_sandbox(mode: str) -> bool:
    return mode == "sandbox"


def is_live(mode: str) -> bool:
    return False


async def dispatch_by_mode(
    live_fn: Callable[..., Awaitable[T]],
    sandbox_fn: Callable[..., Awaitable[T]] | None,
    *args: Any,
    **kwargs: Any,
) -> T:
    if sandbox_fn is None:
        raise RuntimeError("No paper execution handler is available for this operation.")
    return await sandbox_fn(*args, **kwargs)

"""Paper desk and admin-managed customer accounts."""
from datetime import datetime, timezone
import time
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, func, delete
from sqlalchemy.orm import aliased
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.dependencies import get_current_user, get_db
from backend.limiter import limiter
from backend.models.audit import ActiveSession
from backend.models.user import User
from backend.models.sandbox import SandboxFund, SandboxOrder, SandboxPosition, SandboxTrade
from backend.paper.market import get_quote, quote_at
from backend.paper.catalog import INSTRUMENTS, BY_KEY, GROUPS, REFERENCE_ASSETS
from backend.paper.policy import PolicyUpdate, PlatformPolicy, POLICY_KEY, REVISION_KEY, POLICY_LOCK, read_policy_async
from backend.paper.public_prices import snapshot as public_snapshot
from backend.models.settings import AppSettings
from backend.schemas.auth import AccountIdentity, AccountStatus, AssignBroker, BrokerLimit
from backend.paper.hierarchy import issue_invitation, account_can_access
from backend.config import get_settings
from backend.security import hash_password
import secrets

router = APIRouter(prefix="/web/paper", tags=["paper"])


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@router.get("/market")
async def market(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    policy = await read_policy_async(db)
    return {
        "data_source": "synthetic_demo", "paper_only": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "instruments": [{**row, **get_quote(row["symbol"], row["exchange"])} for row in INSTRUMENTS if policy.instrument_enabled(row)],
    }


@router.get("/chart")
async def chart(symbol: str, exchange: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = BY_KEY.get((symbol, exchange))
    if row is None or not (await read_policy_async(db)).instrument_enabled(row):
        raise HTTPException(status_code=404, detail="Instrument unavailable in market watch")
    end = int(time.time() // 60) * 60
    return {"data_source": "synthetic_demo", "points": [
        {"time": timestamp, "value": quote_at(row, timestamp)["ltp"]}
        for timestamp in range(end - 119 * 60, end + 1, 60)
    ]}


def require_manager(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("super_admin", "broker"):
        raise HTTPException(403, "Broker or Super Admin access required")
    return user


def account_dict(row: User, broker_username: str | None = None):
    return dict(id=row.id, username=row.username, email=row.email, role=row.role,
        is_admin=row.is_admin, broker_id=row.broker_id, broker_username=broker_username,
        is_active=row.is_active, password_set=row.password_set, max_users=row.max_users)


def invite_response(row: User, token: str, expires):
    return {**account_dict(row), "invitation_url": get_settings().frontend_url.rstrip("/") + "/invite#token=" + token,
        "expires_at": expires.isoformat()}


async def create_invited_account(data, role, parent_id, db):
    password_hash = await asyncio.to_thread(hash_password, secrets.token_urlsafe(48))
    await db.execute(POLICY_LOCK)
    if role == "user":
        parent = await db.get(User, parent_id, populate_existing=True)
        if parent is None or parent.role != "broker" or not parent.is_active or not parent.password_set:
            raise HTTPException(403, "An active broker must create the user")
    if role == "user":
        await check_broker_capacity(db, parent)
    duplicate = await db.scalar(select(User.id).where((User.username == data.username) | (func.lower(User.email) == str(data.email).lower())))
    if duplicate is not None:
        raise HTTPException(409, "That username or email is already registered")
    if role == "user":
        policy = await read_policy_async(db)
        count = await db.scalar(select(func.count()).select_from(User).where(User.role == "user"))
        if policy.max_customers is not None and count >= policy.max_customers:
            raise HTTPException(409, "Customer account limit reached. Contact Super Admin to increase capacity.")
    row = User(username=data.username, email=str(data.email).lower(), role=role, broker_id=parent_id,
        password_hash=password_hash, password_set=False, is_active=True)
    db.add(row)
    try:
        await db.flush()
        token, expires = await issue_invitation(db, row.id)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "That username or email is already registered") from None
    return invite_response(row, token, expires)


def managed_user_scope(actor: User):
    return (User.role == "user") & (True if actor.role == "super_admin" else User.broker_id == actor.id)


async def check_broker_capacity(db, broker: User) -> None:
    if broker.max_users is not None:
        count = await db.scalar(select(func.count()).select_from(User).where(User.role == "user", User.broker_id == broker.id))
        if count >= broker.max_users:
            raise HTTPException(409, "This broker's user limit has been reached. Contact Super Admin to increase it.")


@router.get("/users")
async def list_users(user: User = Depends(require_manager), db: AsyncSession = Depends(get_db)):
    parent = aliased(User)
    stmt = select(User, parent.username, parent.is_active).outerjoin(parent, parent.id == User.broker_id).where(managed_user_scope(user))
    rows = (await db.execute(stmt.order_by(User.id))).all()
    return [{**account_dict(row, parent_name), "broker_active": parent_active} for row, parent_name, parent_active in rows]


@router.post("/users", status_code=201)
@limiter.limit("20 per hour")
async def create_user(data: AccountIdentity, request: Request,
    user: User = Depends(require_manager), db: AsyncSession = Depends(get_db)):
    if user.role != "broker":
        raise HTTPException(403, "Only brokers can create users. Create a broker first.")
    return await create_invited_account(data, "user", user.id, db)


@router.get("/brokers")
async def list_brokers(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    children = select(User.broker_id, func.count().label("users")).where(User.role == "user").group_by(User.broker_id).subquery()
    rows = (await db.execute(select(User, func.coalesce(children.c.users, 0)).outerjoin(children, children.c.broker_id == User.id)
        .where(User.role == "broker").order_by(User.id))).all()
    return [{**account_dict(row), "users": count} for row, count in rows]


@router.post("/brokers", status_code=201)
@limiter.limit("20 per hour")
async def create_broker(data: AccountIdentity, request: Request,
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return await create_invited_account(data, "broker", None, db)


async def lock_manager(db, actor: User) -> None:
    await db.execute(POLICY_LOCK)
    await db.refresh(actor)
    if not await account_can_access(db, actor):
        raise HTTPException(403, "Account or broker access is disabled")


async def managed_account(db, actor: User, account_id: int) -> User:
    stmt = select(User).where(User.id == account_id)
    if actor.role == "broker":
        stmt = stmt.where(User.role == "user", User.broker_id == actor.id)
    target = await db.scalar(stmt.execution_options(populate_existing=True))
    if target is None:
        raise HTTPException(404, "Account not found")
    if target.role == "super_admin":
        raise HTTPException(403, "Super Admin access cannot be changed here")
    return target


@router.patch("/accounts/{account_id}")
async def set_account_status(account_id: int, data: AccountStatus,
    user: User = Depends(require_manager), db: AsyncSession = Depends(get_db)):
    await lock_manager(db, user)
    target = await managed_account(db, user, account_id)
    target.is_active = data.is_active
    if not data.is_active:
        ids = select(User.id).where((User.id == target.id) | (User.broker_id == target.id))
        await db.execute(delete(ActiveSession).where(ActiveSession.user_id.in_(ids)))
    await db.commit()
    return account_dict(target)


@router.post("/accounts/{account_id}/invitation")
@limiter.limit("20 per hour")
async def replace_invitation(account_id: int, request: Request,
    user: User = Depends(require_manager), db: AsyncSession = Depends(get_db)):
    await lock_manager(db, user)
    target = await managed_account(db, user, account_id)
    if target.password_set or not target.is_active:
        raise HTTPException(409, "Only an enabled account awaiting activation can receive a new invitation")
    token, expires = await issue_invitation(db, target.id)
    await db.commit()
    return invite_response(target, token, expires)


@router.post("/users/{account_id}/assign-broker")
async def assign_legacy_broker(account_id: int, data: AssignBroker,
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    await lock_manager(db, user)
    target = await managed_account(db, user, account_id)
    if target.role != "user" or target.broker_id is not None:
        raise HTTPException(409, "Broker ownership is permanent; only an unassigned legacy user can be assigned")
    parent = await db.get(User, data.broker_id)
    if parent is None or parent.role != "broker" or not parent.is_active or not parent.password_set:
        raise HTTPException(400, "Choose an active broker")
    await check_broker_capacity(db, parent)
    target.broker_id = parent.id
    await db.commit()
    return account_dict(target, parent.username)


@router.get("/admin")
async def admin_overview(user: User = Depends(require_manager), db: AsyncSession = Depends(get_db)):
    positions = select(
        SandboxPosition.user_id,
        func.count().label("open_positions"),
        func.sum(SandboxPosition.unrealized_pnl).label("unrealized_pnl"),
    ).where(SandboxPosition.net_quantity != 0).group_by(SandboxPosition.user_id).subquery()
    orders = select(
        SandboxOrder.user_id, func.count().label("pending_orders"),
    ).where(SandboxOrder.status.in_(["open", "trigger_pending"])).group_by(SandboxOrder.user_id).subquery()
    trades = select(
        SandboxTrade.user_id, func.count().label("fills"),
    ).group_by(SandboxTrade.user_id).subquery()
    rows = (await db.execute(select(
        User.id, User.username, User.email, User.role, User.broker_id, User.is_active, User.password_set,
        SandboxFund.available, SandboxFund.used_margin, SandboxFund.realized_pnl,
        func.coalesce(positions.c.open_positions, 0).label("open_positions"),
        func.coalesce(positions.c.unrealized_pnl, 0).label("unrealized_pnl"),
        func.coalesce(orders.c.pending_orders, 0).label("pending_orders"),
        func.coalesce(trades.c.fills, 0).label("fills"),
    ).outerjoin(SandboxFund, SandboxFund.user_id == User.id)
      .outerjoin(positions, positions.c.user_id == User.id)
      .outerjoin(orders, orders.c.user_id == User.id)
      .outerjoin(trades, trades.c.user_id == User.id)
      .where(True if user.role == "super_admin" else (User.broker_id == user.id) & (User.role == "user"))
      .order_by(User.id))).mappings().all()
    accounts = [{**dict(row), "is_admin": row["role"] == "super_admin"} for row in rows]
    return {
        "paper_only": True, "data_source": "synthetic_demo",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "customers": sum(row["role"] == "user" for row in accounts),
        "open_positions": sum(row["open_positions"] for row in accounts),
        "pending_orders": sum(row["pending_orders"] for row in accounts),
        "fills": sum(row["fills"] for row in accounts),
        "accounts": accounts,
        "broker_max_users": user.max_users if user.role == "broker" else None,
    }


@router.get("/settings")
async def platform_settings(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    policy = await read_policy_async(db)
    count = await db.scalar(select(func.count()).select_from(User).where(User.role == "user"))
    version = await db.scalar(select(AppSettings.value).where(AppSettings.key == REVISION_KEY))
    return {"policy": policy.model_dump(), "revision": int(version or 0), "customer_count": count,
        "groups": GROUPS, "instruments": INSTRUMENTS, "reference_assets": REFERENCE_ASSETS}


@router.put("/settings")
async def update_platform_settings(data: PolicyUpdate, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    await lock_manager(db, user)
    version = await db.scalar(select(AppSettings).where(AppSettings.key == REVISION_KEY).execution_options(populate_existing=True))
    current = int(version.value) if version else 0
    if current != data.revision:
        raise HTTPException(409, "Platform controls changed in another tab. Reload the latest settings before saving.")
    policy = PlatformPolicy.model_validate(data.model_dump(exclude={"revision"}))
    row = await db.scalar(select(AppSettings).where(AppSettings.key == POLICY_KEY).execution_options(populate_existing=True))
    if row is None:
        db.add(AppSettings(key=POLICY_KEY, value=policy.model_dump_json()))
    else:
        row.value = policy.model_dump_json()
    if version is None:
        db.add(AppSettings(key=REVISION_KEY, value=str(current + 1)))
    else:
        version.value = str(current + 1)
    await db.commit()
    return {"policy": policy.model_dump(), "revision": current + 1}


@router.get("/reference-prices")
async def reference_prices(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return public_snapshot(await read_policy_async(db))


@router.patch("/brokers/{broker_id}/limit")
async def set_broker_limit(broker_id: int, data: BrokerLimit,
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    await lock_manager(db, user)
    broker = await db.scalar(select(User).where(User.id == broker_id, User.role == "broker"))
    if broker is None:
        raise HTTPException(404, "Broker not found")
    broker.max_users = data.max_users
    await db.commit()
    return account_dict(broker)


@router.get("/broker-capacity")
async def broker_capacity(user: User = Depends(require_manager), db: AsyncSession = Depends(get_db)):
    if user.role != "broker":
        raise HTTPException(403, "Broker access required")
    count = await db.scalar(select(func.count()).select_from(User).where(managed_user_scope(user)))
    return {"users": count, "max_users": user.max_users}


@router.get("/trades")
async def user_trades(user_id: int | None = Query(None, gt=0),
    before_id: int | None = Query(None, gt=0), limit: int = Query(50, ge=1, le=100),
    user: User = Depends(require_manager), db: AsyncSession = Depends(get_db)):
    if user_id is not None:
        target = await db.scalar(select(User.id).where(managed_user_scope(user), User.id == user_id))
        if target is None:
            raise HTTPException(404, "User not found")
    broker = aliased(User)
    stmt = select(SandboxTrade, User.username, User.broker_id, broker.username).join(User, User.id == SandboxTrade.user_id).outerjoin(broker, broker.id == User.broker_id).where(managed_user_scope(user))
    if user_id is not None:
        stmt = stmt.where(SandboxTrade.user_id == user_id)
    if before_id is not None:
        stmt = stmt.where(SandboxTrade.id < before_id)
    rows = (await db.execute(stmt.order_by(SandboxTrade.id.desc()).limit(limit + 1))).all()
    from backend.sandbox.order_manager import trade_to_dict
    return {"trades": [{**trade_to_dict(trade), "id": trade.id, "user_id": trade.user_id,
        "username": username, "broker_id": parent_id, "broker_username": broker_name,
        "executed_at": trade.timestamp.isoformat()} for trade, username, parent_id, broker_name in rows[:limit]],
        "next_before_id": rows[limit - 1][0].id if len(rows) > limit else None}


@router.get("/earnings")
async def brokerage_earnings(user: User = Depends(require_manager), db: AsyncSession = Depends(get_db)):
    from backend.sandbox.brokerage import earnings
    return await earnings(db, user)

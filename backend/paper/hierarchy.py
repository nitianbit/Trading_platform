"""Account roles, permanent broker ownership, and invitation identity."""
from datetime import datetime, timedelta, timezone
import secrets
from sqlalchemy import select, inspect, text
from backend.models.user import User
from backend.models.invitation import AccountInvitation
from backend.security import hash_api_key


def migrate_hierarchy(engine) -> None:
    with engine.begin() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(2084, 1)"))
        columns = {c["name"] for c in inspect(db).get_columns("users")}
        if "role" not in columns:
            db.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20)"))
            db.execute(text("UPDATE users SET role = CASE WHEN is_admin THEN 'super_admin' ELSE 'user' END"))
            db.execute(text("ALTER TABLE users ALTER COLUMN role SET NOT NULL, ALTER COLUMN role SET DEFAULT 'user'"))
        if "is_admin" in columns:
            # Legacy storage remains compatible; all authorization reads the role column.
            db.execute(text("ALTER TABLE users ALTER COLUMN is_admin SET DEFAULT FALSE"))
        for name, ddl in (("max_users", "INTEGER CHECK (max_users >= 0)"),
                          ("broker_id", "INTEGER REFERENCES users(id) ON DELETE RESTRICT"),
                          ("is_active", "BOOLEAN NOT NULL DEFAULT TRUE"),
                          ("password_set", "BOOLEAN NOT NULL DEFAULT TRUE")):
            if name not in columns:
                db.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_users_broker_id ON users (broker_id)"))
        db.execute(text("""
            CREATE OR REPLACE FUNCTION enforce_paper_account_ownership() RETURNS trigger AS $$
            BEGIN
                IF NEW.role NOT IN ('super_admin', 'broker', 'user') THEN
                    RAISE EXCEPTION 'Invalid account role';
                END IF;
                IF TG_OP = 'UPDATE' THEN
                    IF NEW.role IS DISTINCT FROM OLD.role THEN
                        RAISE EXCEPTION 'Account role is permanent';
                    END IF;
                    IF OLD.broker_id IS NOT NULL AND NEW.broker_id IS DISTINCT FROM OLD.broker_id THEN
                        RAISE EXCEPTION 'Broker ownership is permanent';
                    END IF;
                END IF;
                IF NEW.role = 'user' THEN
                    IF NEW.broker_id IS NULL THEN
                        IF TG_OP = 'INSERT' THEN
                            RAISE EXCEPTION 'New users require a broker';
                        END IF;
                    ELSIF NOT EXISTS (SELECT 1 FROM users WHERE id = NEW.broker_id AND role = 'broker') THEN
                        RAISE EXCEPTION 'User owner must be a broker';
                    END IF;
                ELSIF NEW.broker_id IS NOT NULL THEN
                    RAISE EXCEPTION 'Only users have broker ownership';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """))
        db.execute(text("DROP TRIGGER IF EXISTS paper_account_ownership ON users"))
        db.execute(text("CREATE TRIGGER paper_account_ownership BEFORE INSERT OR UPDATE ON users FOR EACH ROW EXECUTE FUNCTION enforce_paper_account_ownership()"))


async def account_can_access(db, user: User | None) -> bool:
    if user is None or not user.is_active or not user.password_set:
        return False
    if user.role == "user" and user.broker_id is not None:
        parent = await db.get(User, user.broker_id, populate_existing=True)
        return parent is not None and parent.role == "broker" and parent.is_active and parent.password_set
    return user.role in ("super_admin", "broker", "user")


def invitation_hash(token: str) -> str:
    return hash_api_key("account-invitation:" + token)


async def issue_invitation(db, user_id: int) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=48)
    row = await db.get(AccountInvitation, user_id)
    if row is None:
        db.add(AccountInvitation(user_id=user_id, token_hash=invitation_hash(token), expires_at=expires))
    else:
        row.token_hash, row.expires_at, row.accepted_at = invitation_hash(token), expires, None
    return token, expires


async def invitation_account(db, token: str, *, lock: bool = False):
    query = select(AccountInvitation).where(AccountInvitation.token_hash == invitation_hash(token))
    if lock:
        query = query.with_for_update()
    invite = await db.scalar(query.execution_options(populate_existing=True))
    now = datetime.now(timezone.utc)
    if invite is None or invite.accepted_at is not None or invite.expires_at <= now:
        return None, None
    user = await db.get(User, invite.user_id, populate_existing=True)
    if user is None or not user.is_active or user.password_set:
        return None, None
    if user.role == "user":
        parent = await db.get(User, user.broker_id, populate_existing=True) if user.broker_id is not None else None
        if parent is None or parent.role != "broker" or not parent.is_active or not parent.password_set:
            return None, None
    return invite, user

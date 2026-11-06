"""Deployment preflight: do not activate fees over unresolved legacy exposure."""
from sqlalchemy import select
from backend.models.user import User
from backend.models.sandbox import SandboxPosition, SandboxHolding, SandboxOrder

SCHEMA_VERSION = "dhk-2026-11-06-launch-repairs"
SCHEMA_KEY = "paper_schema_version"


def check_legacy_exposure(db) -> None:
    from backend.sandbox.order_validation import SQUAREOFF_CFG_KEY
    for model, active in ((SandboxPosition, SandboxPosition.net_quantity != 0),
                          (SandboxOrder, SandboxOrder.status.in_(["open", "trigger_pending"]))):
        if db.scalar(select(model.id).where(active, model.product == "MIS", model.exchange.not_in(list(SQUAREOFF_CFG_KEY))).limit(1)) is not None:
            raise RuntimeError("Launch blocked: unsupported MIS exposure has no automatic square-off; close or cancel it before deployment. No books were changed.")
    unassigned = select(User.id).where(User.role == "user", User.broker_id.is_(None))
    positions = db.scalar(select(SandboxPosition.id).where(SandboxPosition.user_id.in_(unassigned), SandboxPosition.net_quantity != 0).limit(1))
    orders = db.scalar(select(SandboxOrder.id).where(SandboxOrder.user_id.in_(unassigned), SandboxOrder.status.in_(["open", "trigger_pending"])).limit(1))
    if positions is not None or orders is not None:
        raise RuntimeError("Launch blocked: assign legacy users with exposure to a broker before enabling brokerage. No fee-free exits are introduced.")
    if db.scalar(select(SandboxHolding.id).where(SandboxHolding.quantity != 0).limit(1)) is not None:
        raise RuntimeError("Launch blocked: existing delivery holdings require reconciliation before CNC can be disabled. No inventory or cash was changed.")


def require_migrated(engine) -> None:
    from sqlalchemy import inspect
    from sqlalchemy.orm import Session
    from backend.models.settings import AppSettings
    if "app_settings" not in inspect(engine).get_table_names():
        raise RuntimeError("Run scripts/migrate_database.py with a verified backup before production startup")
    with Session(engine) as db:
        version = db.scalar(select(AppSettings.value).where(AppSettings.key == SCHEMA_KEY))
        if version != SCHEMA_VERSION:
            raise RuntimeError("Run scripts/migrate_database.py with a verified backup before production startup")
        check_legacy_exposure(db)

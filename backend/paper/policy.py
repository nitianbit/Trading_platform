"""Persistent platform policy; enforced by both HTTP admission and the order ledger."""
from contextlib import nullcontext
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from backend.models.settings import AppSettings
from backend.models.sandbox import SandboxPosition
from backend.paper.catalog import BY_KEY, GROUPS, REFERENCE_SYMBOLS, instrument_key
from backend.sandbox._db import session_scope

POLICY_KEY = "paper_platform_policy"
REVISION_KEY = "paper_platform_policy_revision"
# Customer admission and policy writes serialize across processes, including an absent row.
POLICY_LOCK = text("SELECT pg_advisory_xact_lock(2084, 0)")


class PlatformPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_customers: int | None = Field(default=None, ge=0, le=2147483647)
    disabled_groups: list[str] = Field(default_factory=list)
    disabled_instruments: list[str] = Field(default_factory=list)
    public_feed_enabled: bool = True
    disabled_reference_assets: list[str] = Field(default_factory=list)

    @field_validator("disabled_groups", "disabled_instruments", "disabled_reference_assets")
    @classmethod
    def known_values(cls, values, info):
        allowed = {"disabled_groups": set(GROUPS),
            "disabled_instruments": {f"{exchange}:{symbol}" for symbol, exchange in BY_KEY},
            "disabled_reference_assets": REFERENCE_SYMBOLS}[info.field_name]
        if set(values) - allowed:
            raise ValueError("Unknown market or instrument identifier")
        return sorted(set(values))

    def instrument_enabled(self, row: dict) -> bool:
        return row["group"] not in self.disabled_groups and instrument_key(row) not in self.disabled_instruments


class PolicyUpdate(PlatformPolicy):
    # Internal defaults are useful for fresh installations; HTTP replacement
    # requires the complete document and the version actually edited.
    max_customers: int | None = Field(ge=0, le=2147483647)
    disabled_groups: list[str]
    disabled_instruments: list[str]
    public_feed_enabled: bool
    disabled_reference_assets: list[str]
    revision: int = Field(ge=0)


def parse_policy(row: AppSettings | None) -> PlatformPolicy:
    return PlatformPolicy.model_validate_json(row.value) if row is not None else PlatformPolicy()


def read_policy(db: Session | None = None) -> PlatformPolicy:
    with (nullcontext(db) if db is not None else session_scope()) as db:
        return parse_policy(db.scalar(select(AppSettings).where(AppSettings.key == POLICY_KEY)))


async def read_policy_async(db) -> PlatformPolicy:
    return parse_policy(await db.scalar(select(AppSettings).where(AppSettings.key == POLICY_KEY)))


def order_access(*, db: Session | None, user_id: int, symbol: str, exchange: str,
                 product: str, action: str, quantity: int) -> tuple[bool, str]:
    with (nullcontext(db) if db is not None else session_scope()) as db:
        row = BY_KEY.get((symbol, exchange))
        net = db.scalar(select(SandboxPosition.net_quantity).where(
            SandboxPosition.user_id == user_id, SandboxPosition.symbol == symbol,
            SandboxPosition.exchange == exchange, SandboxPosition.product == product)) or 0
        reducing = (net > 0 and action == "SELL") or (net < 0 and action == "BUY")
        reduction = reducing and 0 < quantity <= abs(net)
        if product == "CNC" and not reduction:
            return False, "CNC delivery trading is unavailable; equity supports MIS only. Existing positions can be reduced or closed."
        from backend.sandbox.order_validation import SQUAREOFF_CFG_KEY
        if product == "MIS" and exchange not in SQUAREOFF_CFG_KEY and not reduction:
            return False, f"MIS is unavailable on {exchange}; use NRML. Existing positions can be reduced or closed."
        if row is not None and read_policy(db).instrument_enabled(row):
            return True, ""
        if reduction:
            return True, ""
        return False, "This instrument is disabled for new entries; existing positions may only be reduced or closed"

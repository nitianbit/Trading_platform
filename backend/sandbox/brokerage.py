"""Exact-paise, per-fill brokerage; this ledger owns fee and recipient facts."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from sqlalchemy import select, func
from backend.models.user import User
from backend.models.sandbox import SandboxBrokerage


@dataclass(frozen=True)
class Charge:
    broker_id: int
    admin_id: int
    notional_paise: int
    fee_paise: int
    broker_paise: int
    admin_paise: int


def split_paise(price: float, quantity: int) -> tuple[int, int, int, int]:
    value = Decimal(str(price)) * quantity
    # The accounting columns are signed BIGINT paise; reject unsupported notionals before allocation.
    if not value.is_finite() or value < 0 or value > Decimal("92233720368547758.07"):
        raise ValueError("Trade value exceeds the supported monetary range")
    def rounded(amount):
        return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    try:
        notional = rounded(value * 100)
        fee = rounded(value * 4)
        broker = rounded(Decimal(fee) * Decimal("0.75"))
    except InvalidOperation:
        raise ValueError("Invalid trade value") from None
    return notional, fee, broker, fee - broker


def quote_charge(db, user_id: int, price: float, quantity: int) -> Charge | None:
    user = db.get(User, user_id)
    if user is None:
        raise ValueError("Platform account not found")
    if user.role != "user":
        return None
    parent = db.get(User, user.broker_id) if user.broker_id is not None else None
    if parent is None or parent.role != "broker":
        raise ValueError("Assign this user to a broker before trading so brokerage can be credited")
    admin_id = db.scalar(select(User.id).where(User.role == "super_admin").order_by(User.id).limit(1))
    if admin_id is None:
        raise ValueError("Super Admin brokerage account is unavailable")
    return Charge(parent.id, admin_id, *split_paise(price, quantity))


def record_charge(db, user_id: int, tradeid: str, charge: Charge | None):
    if charge is None:
        return None
    row = SandboxBrokerage(user_id=user_id, tradeid=tradeid, **charge.__dict__)
    db.add(row)
    return row


def fee_fields(row: SandboxBrokerage | None) -> dict:
    return {"brokerage": (row.fee_paise if row else 0) / 100,
        "broker_credit": (row.broker_paise if row else 0) / 100,
        "admin_credit": (row.admin_paise if row else 0) / 100}


async def earnings(db, actor: User) -> dict:
    share = SandboxBrokerage.broker_paise if actor.role == "broker" else SandboxBrokerage.admin_paise
    owner = SandboxBrokerage.broker_id if actor.role == "broker" else SandboxBrokerage.admin_id
    amount = int(await db.scalar(select(func.coalesce(func.sum(share), 0)).where(owner == actor.id)))
    return {"balance_paise": amount, "balance": amount / 100, "currency": "INR", "virtual": True,
        "rate_percent": 3 if actor.role == "broker" else 1}

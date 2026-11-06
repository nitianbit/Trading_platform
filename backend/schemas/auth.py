import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def valid_username(value: str) -> str:
    value = value.strip().lower()
    if not 3 <= len(value) <= 80 or re.fullmatch(r"[a-z0-9_]+", value) is None:
        raise ValueError("Username must be 3-80 letters, digits or underscores")
    return value


def valid_password(value: str) -> str:
    if not 8 <= len(value) <= 128:
        raise ValueError("Password must be 8-128 characters")
    return value


class AccountIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(max_length=80)
    email: EmailStr = Field(max_length=120)
    _username = field_validator("username")(valid_username)


class SetupRequest(AccountIdentity):
    setup_token: str = Field(default="", max_length=256)
    password: str
    _password = field_validator("password")(valid_password)


class InvitationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=128)


class AcceptInvitation(InvitationRequest):
    password: str
    _password = field_validator("password")(valid_password)


class AccountStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    is_active: bool


class AssignBroker(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    broker_id: int = Field(gt=0)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


class AuthResponse(BaseModel):
    status: str
    message: str


class UserInfo(BaseModel):
    id: int
    username: str
    email: str
    role: Literal["super_admin", "broker", "user"]
    is_admin: bool
    broker_id: int | None = None
    broker_username: str | None = None
    broker: str | None = None
    broker_authenticated: bool = False
    paper_only: bool = True


class BrokerLimit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_users: int | None = Field(ge=0, le=2147483647)

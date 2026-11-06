import logging
import asyncio
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import async_session
from backend.dependencies import get_db, get_current_user, invalidate_user_cache
from backend.limiter import limiter
from backend.models.user import User
from backend.models.auth import ApiKey
from backend.models.audit import LoginAttempt, ActiveSession
from backend.schemas.auth import SetupRequest, LoginRequest, AuthResponse, UserInfo, InvitationRequest, AcceptInvitation
from backend.paper.hierarchy import account_can_access, invitation_account
from backend.security import (
    hash_password, verify_password, check_needs_rehash, create_access_token,
    generate_api_key, hash_api_key, encrypt_value, decrypt_value,
)

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/auth", tags=["auth"])

# Pre-computed Argon2 hash over a random throwaway secret, used to equalize
# response time when the submitted username doesn't exist. Without this,
# /auth/login leaks username existence through timing (Argon2 verify takes
# ~100s of ms; short-circuiting leaks the answer).
_TIMING_DUMMY_HASH = hash_password(secrets.token_hex(16))


@router.get("/check-setup")
async def check_setup(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(func.count()).select_from(User))
    user_count = result.scalar()
    return {"needs_setup": user_count == 0}


@router.post("/setup", response_model=AuthResponse)
@limiter.limit("5 per hour")
async def setup(data: SetupRequest, request: Request, db: AsyncSession = Depends(get_db)):
    if len(settings.setup_token) < 32 or not secrets.compare_digest(data.setup_token, settings.setup_token):
        raise HTTPException(status_code=403, detail="A valid operator setup token is required")
    from sqlalchemy import text
    await db.execute(text("SELECT pg_advisory_xact_lock(2082, 0)"))
    # Only allow setup if no users exist
    result = await db.execute(select(func.count()).select_from(User))
    if result.scalar() > 0:
        raise HTTPException(status_code=403, detail="Setup already completed. Only one admin user is allowed.")

    user = User(
        username=data.username,
        email=data.email,
        password_hash=await asyncio.to_thread(hash_password, data.password),
        is_admin=True,
    )
    db.add(user)
    await db.flush()  # Get user.id before committing

    # Auto-generate API key for the new admin user
    new_api_key = generate_api_key()
    db.add(ApiKey(
        user_id=user.id,
        api_key_hash=hash_api_key(new_api_key),
        api_key_encrypted=encrypt_value(new_api_key),
    ))

    await db.commit()
    logger.info("Admin user '%s' created during setup with API key", data.username)
    return AuthResponse(status="success", message="Admin account created. Please login.")


@router.post("/login", response_model=AuthResponse)
async def login(data: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    from backend.api_limits import check_login_rate
    await check_login_rate(request, data.username)
    ip_address = request.client.host if request.client else "unknown"
    device_info = request.headers.get("User-Agent", "")[:500]

    result = await db.execute(select(User).where(User.username == data.username.strip().lower()))
    user = result.scalar_one_or_none()

    # Always run Argon2 verify — even when the user is absent — so the
    # response time does not reveal whether the username exists.
    password_ok = await asyncio.to_thread(verify_password,
        data.password,
        user.password_hash if user else _TIMING_DUMMY_HASH,
    )

    if not user or not password_ok or not await account_can_access(db, user):
        # Log failed attempt
        db.add(LoginAttempt(
            username=data.username,
            ip_address=ip_address,
            device_info=device_info,
            status="failed",
            login_type="password",
            failure_reason="invalid_credentials",
        ))
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Rehash if needed
    if check_needs_rehash(user.password_hash):
        user.password_hash = await asyncio.to_thread(hash_password, data.password)

    broker_name = None

    # Generate an ActiveSession row up front; the JWT carries its token as
    # `jti`, and get_current_user requires that the row still exist. This
    # turns logout (which deletes the row) into real server-side revocation
    # and makes "log out all devices" actually invalidate stolen cookies.
    session_token = secrets.token_hex(32)

    token = create_access_token(data={
        "sub": str(user.id),
        "username": user.username,
        "broker": broker_name,
        "jti": session_token,
    })

    # Log success
    db.add(LoginAttempt(
        username=user.username,
        ip_address=ip_address,
        device_info=device_info,
        status="success",
        login_type="password",
        broker=broker_name,
    ))

    # Track session
    db.add(ActiveSession(
        user_id=user.id,
        session_token=session_token,
        device_info=device_info,
        ip_address=ip_address,
        broker=broker_name,
    ))
    await db.commit()

    # Set httpOnly cookie
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )

    return AuthResponse(status="success", message="Login successful")


@router.post("/logout", response_model=AuthResponse)
@limiter.limit("30 per minute")
async def logout(response: Response, request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get("access_token")
    if token:
        from backend.security import decode_access_token
        payload = decode_access_token(token)
        if payload:
            user_id = payload.get("sub")
            if user_id:
                # Clear sessions
                result = await db.execute(
                    select(ActiveSession).where(ActiveSession.user_id == int(user_id))
                )
                for session in result.scalars().all():
                    await db.delete(session)
                await db.commit()

                # Clear cached broker context for this user
                from backend.dependencies import invalidate_user_cache
                await invalidate_user_cache(int(user_id))

    response.delete_cookie(
        "access_token",
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return AuthResponse(status="success", message="Logged out")


@router.get("/me", response_model=UserInfo)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    parent = await db.get(User, user.broker_id) if user.broker_id is not None else None
    return UserInfo(
        id=user.id, username=user.username, email=user.email, role=user.role, is_admin=user.is_admin,
        broker_id=user.broker_id, broker_username=parent.username if parent else None,
        broker=None, broker_authenticated=False, paper_only=True,
    )


@router.post("/invite/preview")
@limiter.limit("30 per minute")
async def preview_invitation(data: InvitationRequest, request: Request, db: AsyncSession = Depends(get_db)):
    _, user = await invitation_account(db, data.token)
    if user is None:
        raise HTTPException(400, "Invitation is invalid, expired, used, or disabled. Ask the sender for a new link.")
    parent = await db.get(User, user.broker_id) if user.broker_id is not None else None
    return {"username": user.username, "email": user.email, "role": user.role,
        "broker_username": parent.username if parent else None}


@router.post("/invite/accept", response_model=AuthResponse)
@limiter.limit("20 per minute")
async def accept_invitation(data: AcceptInvitation, request: Request, db: AsyncSession = Depends(get_db)):
    # Verify before Argon work, then lock and recheck to prevent concurrent token replay.
    _, candidate = await invitation_account(db, data.token)
    if candidate is None:
        raise HTTPException(400, "Invitation is invalid, expired, used, or disabled. Ask the sender for a new link.")
    password_hash = await asyncio.to_thread(hash_password, data.password)
    from backend.paper.policy import POLICY_LOCK
    await db.execute(POLICY_LOCK)
    invite, user = await invitation_account(db, data.token, lock=True)
    if user is None:
        raise HTTPException(400, "Invitation is invalid, expired, used, or disabled. Ask the sender for a new link.")
    from datetime import datetime, timezone
    invite.accepted_at = datetime.now(timezone.utc)
    user.password_hash, user.password_set = password_hash, True
    key = generate_api_key()
    db.add(ApiKey(user_id=user.id, api_key_hash=hash_api_key(key), api_key_encrypted=encrypt_value(key)))
    await db.commit()
    return AuthResponse(status="success", message="Account activated. You can now sign in.")

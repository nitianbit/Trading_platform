import hashlib
import hmac
import base64
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
import jwt
from jwt import InvalidTokenError

from backend.config import get_settings

settings = get_settings()

# -- Argon2 password hashing --

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    peppered = password + settings.encryption_pepper
    return _ph.hash(peppered)


def verify_password(password: str, password_hash: str) -> bool:
    peppered = password + settings.encryption_pepper
    try:
        return _ph.verify(password_hash, peppered)
    except VerifyMismatchError:
        return False


def check_needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


# -- Fernet encryption (for tokens, broker secrets) --

def _derive_fernet_key() -> bytes:
    pepper = settings.encryption_pepper.encode()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"openbull_static_salt",
        iterations=100_000,
    )
    key = kdf.derive(pepper)
    return base64.urlsafe_b64encode(key)


_fernet = Fernet(_derive_fernet_key())


def encrypt_value(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()


# -- Random API keys: indexed HMAC-SHA256, passwords remain Argon2 --

def hash_api_key(api_key: str) -> str:
    return hmac.new(settings.encryption_pepper.encode(), api_key.encode(), hashlib.sha256).hexdigest()


def verify_api_key(api_key: str, api_key_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(api_key), api_key_hash)


def migrate_api_keys(engine) -> None:
    """Preserve existing keys while replacing their legacy Argon2 verifiers."""
    from sqlalchemy import select, text
    from sqlalchemy.orm import Session
    from backend.models.auth import ApiKey
    with Session(engine) as db, db.begin():
        db.execute(text("SELECT pg_advisory_xact_lock(2082, 0)"))
        for record in db.scalars(select(ApiKey).where(ApiKey.api_key_hash.like("$argon2%")).with_for_update()):
            record.api_key_hash = hash_api_key(decrypt_value(record.api_key_encrypted))
        db.flush()
        db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys (api_key_hash)"))


def generate_api_key() -> str:
    return secrets.token_hex(32)


# -- JWT --

ALGORITHM = "HS256"


def create_access_token(
    data: dict,
    expires_delta: timedelta | None = None,
) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        # Default: expire at 3:00 AM IST next day
        now_utc = datetime.now(timezone.utc)
        ist_offset = timedelta(hours=5, minutes=30)
        now_ist = now_utc + ist_offset

        parts = settings.session_expiry_time.split(":")
        expiry_hour, expiry_min = int(parts[0]), int(parts[1])

        expiry_ist = now_ist.replace(hour=expiry_hour, minute=expiry_min, second=0, microsecond=0)
        if expiry_ist <= now_ist:
            expiry_ist += timedelta(days=1)

        expire = expiry_ist - ist_offset  # convert back to UTC

    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.app_secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.app_secret_key, algorithms=[ALGORITHM])
        return payload
    except InvalidTokenError:
        return None

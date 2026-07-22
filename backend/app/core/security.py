"""
BreatheSafe — Security Utilities
Password hashing (bcrypt) and JWT token creation / verification.

Note: Uses bcrypt directly instead of passlib to avoid the passlib 1.7.4 +
bcrypt 4.x incompatibility (passlib's detect_wrap_bug calls hashpw with a
>72-byte string which bcrypt 4.x rejects).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from app.config import settings


# ── Bcrypt helpers ─────────────────────────────────────────────────────────────
def hash_password(plain: str) -> str:
    """Return bcrypt hash of the plain-text password."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """
    Return True if plain matches the stored bcrypt hash.

    bcrypt raises ValueError on inputs over 72 bytes and on malformed hashes;
    a failed comparison is an authentication failure, not a server error, so
    those surface as False rather than propagating into a 500.
    """
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── JWT helpers ────────────────────────────────────────────────────────────────
def _make_token(subject: str, expires_delta: timedelta, token_type: str) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": subject,
        "exp": expire,
        "type": token_type,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: int) -> str:
    return _make_token(
        subject=str(user_id),
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        token_type="access",
    )


def create_refresh_token(user_id: int) -> str:
    return _make_token(
        subject=str(user_id),
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        token_type="refresh",
    )


def decode_token(token: str) -> Optional[dict]:
    """
    Decode and validate a JWT.
    Returns the payload dict on success, None on any failure.
    """
    try:
        return jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError:
        return None

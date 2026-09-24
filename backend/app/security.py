"""Password hashing and JWT session cookies."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Response

from .config import settings

ALGORITHM = "HS256"
# bcrypt hashes at most 72 bytes; longer passwords are rejected in the schema layer.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.SESSION_DAYS)).timestamp()),
        # Microsecond-resolution mint time, for session invalidation only.
        # `iat` above is second-resolution (standard JWT NumericDate) and is
        # too coarse to reliably order against a password-change cutoff that
        # can land in the very same second.
        "session_started": now.isoformat(timespec="microseconds"),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token_full(token: str) -> dict | None:
    """The whole payload, for callers that need `iat` as well as `sub`."""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


def set_session_cookie(response: Response, user_id: int) -> None:
    response.set_cookie(
        key=settings.COOKIE_NAME,
        value=create_token(user_id),
        max_age=settings.SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.COOKIE_NAME, path="/")

"""Authentication dependencies."""

from __future__ import annotations

import sqlite3

from fastapi import Depends, HTTPException, Request, status

from .config import settings
from .db import get_conn
from .security import decode_token_full


def _user_from_request(request: Request) -> sqlite3.Row | None:
    token = request.cookies.get(settings.COOKIE_NAME)
    if not token:
        return None
    payload = decode_token_full(token)
    if not payload:
        return None
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None
    with get_conn() as conn:
        user = conn.execute(
            "SELECT id, email, created_at, role, full_name, first_name, last_name, phone,"
            " is_active, theme, sessions_valid_from"
            " FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if user is None:
        return None
    # A password change stamps sessions_valid_from; tokens minted before it die.
    # Both sides are microsecond-resolution ISO strings (see create_token's
    # `session_started` claim and db.utcnow_precise), so same-second races
    # between the cutoff and a token's mint time still compare correctly.
    # A token from before this claim existed has no `session_started` and is
    # treated as arbitrarily old, i.e. invalidated by any cutoff.
    cutoff = user["sessions_valid_from"]
    if cutoff:
        issued = payload.get("session_started") or ""
        if issued < cutoff:
            return None
    return user


def get_current_user(request: Request) -> sqlite3.Row:
    """For API routes: 401 when the session is missing or invalid."""
    user = _user_from_request(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    return user


def get_optional_user(request: Request) -> sqlite3.Row | None:
    """For page routes: caller decides whether to redirect."""
    return _user_from_request(request)


def require_trainer(user: sqlite3.Row = Depends(get_current_user)) -> sqlite3.Row:
    """Role-based access control (SRS §20): trainer-only endpoints."""
    if user["role"] != "trainer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Trainer access only."
        )
    return user


def require_student(user: sqlite3.Row = Depends(get_current_user)) -> sqlite3.Row:
    if user["role"] != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Student access only."
        )
    return user

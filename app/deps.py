"""Authentication dependencies."""

from __future__ import annotations

import sqlite3

from fastapi import HTTPException, Request, status

from .config import settings
from .db import get_conn
from .security import decode_token


def _user_from_request(request: Request) -> sqlite3.Row | None:
    token = request.cookies.get(settings.COOKIE_NAME)
    if not token:
        return None
    user_id = decode_token(token)
    if user_id is None:
        return None
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()


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

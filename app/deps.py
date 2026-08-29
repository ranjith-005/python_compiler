"""Authentication dependencies."""

from __future__ import annotations

import sqlite3

from fastapi import Depends, HTTPException, Request, status

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
            "SELECT id, email, created_at, role, full_name, first_name, last_name, phone, is_active"
            " FROM users WHERE id = ?",
            (user_id,),
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

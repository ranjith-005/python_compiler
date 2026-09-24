"""Authentication dependencies."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from fastapi import Depends, HTTPException, Request, status

from .config import settings
from .db import get_conn, utcnow
from .security import decode_token_full

# How stale a `last_seen_at` stamp may get before the next authenticated
# request refreshes it. Presence on the roster is a five-minute window, so a
# minute of drift costs nothing and keeps this off the write path of most
# requests.
PRESENCE_REFRESH_SEC = 60


def user_from_token(token: str | None) -> sqlite3.Row | None:
    """Resolve a session token to its user, honouring the password-change cutoff.

    Shared by the HTTP path and the websocket handshake. The socket used to call
    decode_token directly, which skipped the cutoff entirely and left the
    code-execution channel open to a cookie the password change had revoked.
    """
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
            " is_active, theme, sessions_valid_from, last_seen_at"
            " FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if user is None:
        return None
    if not user["is_active"]:
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
    _touch_last_seen(user)
    return user


def _touch_last_seen(user: sqlite3.Row) -> None:
    """Refresh the presence stamp the trainer's roster reads.

    Throttled: a stamp younger than PRESENCE_REFRESH_SEC is left alone, so a
    page that fires several authenticated requests writes at most once.
    """
    now = utcnow()
    previous = user["last_seen_at"] or ""
    if previous:
        try:
            age = (
                datetime.fromisoformat(now) - datetime.fromisoformat(previous)
            ).total_seconds()
        except ValueError:
            age = PRESENCE_REFRESH_SEC + 1
        if age < PRESENCE_REFRESH_SEC:
            return
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE users SET last_seen_at = ? WHERE id = ?", (now, user["id"])
            )
    except sqlite3.Error:
        # Presence is decoration. A locked database must not fail the request
        # that was only trying to read the page.
        pass


def _user_from_request(request: Request) -> sqlite3.Row | None:
    return user_from_token(request.cookies.get(settings.COOKIE_NAME))


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

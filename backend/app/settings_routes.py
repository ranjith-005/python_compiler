"""Account preferences: appearance and personal details.

Separate from `auth.py`, which owns credentials and sessions.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from .db import get_conn
from .deps import get_current_user
from .names import display_name
from .schemas import ProfileIn, ThemeIn

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _profile_payload(row: sqlite3.Row | dict) -> dict:
    return {
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "phone": row["phone"],
        "full_name": row["full_name"],
        "display_name": display_name(row),
        "email": row["email"],
        "theme": row["theme"],
    }


@router.get("/profile")
def read_profile(user: sqlite3.Row = Depends(get_current_user)) -> dict:
    return _profile_payload(user)


@router.patch("/profile")
def update_profile(
    body: ProfileIn, user: sqlite3.Row = Depends(get_current_user)
) -> dict:
    first = body.first_name.strip()
    last = body.last_name.strip()
    full = f"{first} {last}".strip()
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET first_name = ?, last_name = ?, phone = ?, full_name = ?"
            " WHERE id = ?",
            (first, last, body.phone.strip(), full, user["id"]),
        )
        row = conn.execute(
            "SELECT email, full_name, first_name, last_name, phone, theme"
            " FROM users WHERE id = ?",
            (user["id"],),
        ).fetchone()
    return _profile_payload(row)


@router.patch("/theme")
def update_theme(body: ThemeIn, user: sqlite3.Row = Depends(get_current_user)) -> dict:
    with get_conn() as conn:
        conn.execute("UPDATE users SET theme = ? WHERE id = ?", (body.theme, user["id"]))
    return {"theme": body.theme}

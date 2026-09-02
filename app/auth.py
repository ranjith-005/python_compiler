"""Registration, login, logout."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response, status

from .db import WELCOME_CELLS, create_notebook, get_conn, utcnow
from .deps import get_current_user
from .schemas import Credentials, PasswordChangeIn
from .security import (
    clear_session_cookie,
    hash_password,
    set_session_cookie,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def home_for(role: str) -> str:
    """Where a signed-in user lands (SRS §1: separate trainer/student portals)."""
    return "/trainer" if role == "trainer" else "/student"


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(creds: Credentials, response: Response) -> dict:
    email = creds.email.strip().lower()
    now = utcnow()
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, created_at, role, full_name, first_name, last_name, phone)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    email,
                    hash_password(creds.password),
                    now,
                    creds.role,
                    f"{creds.first_name.strip()} {creds.last_name.strip()}".strip()
                    or creds.full_name.strip(),
                    creds.first_name.strip(),
                    creds.last_name.strip(),
                    creds.phone.strip(),
                ),
            )
            user_id = int(cur.lastrowid)
            create_notebook(conn, user_id, "Welcome.ipynb", WELCOME_CELLS)
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )
    set_session_cookie(response, user_id)
    return {"id": user_id, "email": email, "role": creds.role, "home": home_for(creds.role)}


@router.post("/login")
def login(creds: Credentials, response: Response) -> dict:
    email = creds.email.strip().lower()
    with get_conn() as conn:
        user = conn.execute(
            "SELECT id, email, password_hash, role, is_active FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    # Same message either way - don't reveal which emails are registered.
    if user is None or not verify_password(creds.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Contact your trainer.",
        )
    set_session_cookie(response, int(user["id"]))
    return {
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "home": home_for(user["role"]),
    }


@router.post("/logout")
def logout(response: Response) -> dict:
    clear_session_cookie(response)
    return {"ok": True}


@router.post("/password")
def change_password(
    body: PasswordChangeIn,
    response: Response,
    user: sqlite3.Row = Depends(get_current_user),
) -> dict:
    """Change your own password (settings requirement 6, both roles)."""
    if body.new_password != body.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The new passwords do not match.",
        )
    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a password different from your current one.",
        )

    with get_conn() as conn:
        # get_current_user deliberately does not carry the hash around.
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user["id"],)
        ).fetchone()
        # 400, not 401: a wrong password here is a form error, not an expired session.
        if row is None or not verify_password(body.current_password, row["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your current password is not correct.",
            )
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(body.new_password), user["id"]),
        )

    # Keep the user signed in on this device.
    set_session_cookie(response, int(user["id"]))
    return {"ok": True}


@router.get("/me")
def me(user: sqlite3.Row = Depends(get_current_user)) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "full_name": user["full_name"],
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "phone": user["phone"],
        "theme": user["theme"],
        "home": home_for(user["role"]),
    }

"""Registration, login, logout."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response, status

from .db import WELCOME_CELLS, create_notebook, get_conn, utcnow
from .deps import get_current_user
from .schemas import Credentials
from .security import (
    clear_session_cookie,
    hash_password,
    set_session_cookie,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(creds: Credentials, response: Response) -> dict:
    email = creds.email.strip().lower()
    now = utcnow()
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (email, hash_password(creds.password), now),
            )
            user_id = int(cur.lastrowid)
            create_notebook(conn, user_id, "Welcome.ipynb", WELCOME_CELLS)
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )
    set_session_cookie(response, user_id)
    return {"id": user_id, "email": email}


@router.post("/login")
def login(creds: Credentials, response: Response) -> dict:
    email = creds.email.strip().lower()
    with get_conn() as conn:
        user = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
    # Same message either way - don't reveal which emails are registered.
    if user is None or not verify_password(creds.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    set_session_cookie(response, int(user["id"]))
    return {"id": user["id"], "email": user["email"]}


@router.post("/logout")
def logout(response: Response) -> dict:
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(user: sqlite3.Row = Depends(get_current_user)) -> dict:
    return {"id": user["id"], "email": user["email"]}

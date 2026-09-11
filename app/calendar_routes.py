"""The calendar: online sessions, and the marks people make for themselves.

Deadlines are not here. They are derived from `assignments` by whichever
dashboard is asking, because storing a copy would create a second answer to
"when is this due" and the two would drift the first time a due date moved.
What this module owns is everything the rest of the schema does not know:

    an online session   a trainer schedules it; every student sees it
    a personal note     its owner made it for themselves; nobody else sees it

That distinction is the whole access rule, and it is enforced on read
(`_visible_to`) as well as on write, so a student cannot reach a trainer's
private note by guessing an id any more than by listing the month.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from .db import get_conn, utcnow
from .deps import get_current_user
from .schemas import CalendarEventIn

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

# What a trainer may create. A student gets the personal note only: sessions
# are the trainer's to schedule, and letting a student post one would put a
# class on every other student's calendar.
TRAINER_KINDS = ("personal", "session")
STUDENT_KINDS = ("personal",)


def _row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "title": row["title"],
        "description": row["description"],
        "event_date": row["event_date"],
        "owner_id": row["owner_id"],
        "mine": None,  # filled in by the caller, which knows who is asking
    }


def _visible_to(conn: sqlite3.Connection, user: sqlite3.Row) -> list[dict]:
    """Every event this person may see: their own, plus scheduled sessions.

    One query rather than two so the ordering is the database's job. A trainer
    sees their own sessions through the `owner_id` arm, not a second rule.
    """
    viewer = int(user["id"])
    rows = conn.execute(
        "SELECT id, owner_id, kind, title, description, event_date"
        " FROM calendar_events"
        " WHERE owner_id = ? OR kind = 'session'"
        " ORDER BY event_date ASC, id ASC",
        (viewer,),
    ).fetchall()
    out = []
    for row in rows:
        item = _row(row)
        item["mine"] = int(row["owner_id"]) == viewer
        out.append(item)
    return out


@router.get("")
def list_events(user: sqlite3.Row = Depends(get_current_user)) -> dict:
    """Everything on this viewer's calendar.

    Unpaged and unfiltered by month on purpose: these are a handful of rows a
    person typed themselves, and the month buttons move through data the
    browser already holds rather than asking again for every arrow press.
    """
    with get_conn() as conn:
        return {"events": _visible_to(conn, user)}


@router.post("", status_code=201)
def create_event(
    body: CalendarEventIn, user: sqlite3.Row = Depends(get_current_user)
) -> dict:
    """Mark a date. A student may only mark it for themselves."""
    allowed = TRAINER_KINDS if user["role"] == "trainer" else STUDENT_KINDS
    if body.kind not in allowed:
        raise HTTPException(
            status_code=403,
            detail="Only a trainer can schedule an online session.",
        )

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO calendar_events"
            " (owner_id, kind, title, description, event_date, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (int(user["id"]), body.kind, body.title.strip(),
             body.description.strip(), body.event_date, utcnow()),
        )
        row = conn.execute(
            "SELECT id, owner_id, kind, title, description, event_date"
            " FROM calendar_events WHERE id = ?",
            (int(cur.lastrowid),),
        ).fetchone()

    event = _row(row)
    event["mine"] = True
    return event


@router.delete("/{event_id}")
def delete_event(
    event_id: int, user: sqlite3.Row = Depends(get_current_user)
) -> dict:
    """Remove one of your own marks.

    Ownership, not role: a trainer cannot delete another trainer's session,
    and the 404 is deliberate -- someone probing ids learns nothing about
    whether the row exists.
    """
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM calendar_events WHERE id = ? AND owner_id = ?",
            (event_id, int(user["id"])),
        )
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="No such event.")
    return {"deleted": event_id}

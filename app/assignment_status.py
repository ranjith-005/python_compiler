"""Canonical assignment lifecycle statuses (per student, per exercise).

Stored on ``assignments.status``:

- assigned     — assigned, not opened yet
- in_progress  — student opened / started work
- submitted    — submitted to trainer for review
- pending      — due date passed, not submitted for review
- completed    — trainer approved / marked complete
"""

from __future__ import annotations

import sqlite3

from .db import utcnow

ASSIGNMENT_STATUSES = ("assigned", "in_progress", "submitted", "pending", "completed")

# Still active before trainer closes the exercise (may include overdue ``pending``).
ACTIVE_STATUSES = ("assigned", "in_progress", "pending")

# Can flip to ``pending`` when the due date passes without a submission.
PRE_SUBMIT_STATUSES = ("assigned", "in_progress")

ACTIVE_LIST = ",".join("?" * len(ACTIVE_STATUSES))
PRE_SUBMIT_LIST = ",".join("?" * len(PRE_SUBMIT_STATUSES))


def sync_overdue_assignments(conn: sqlite3.Connection, now: str | None = None) -> None:
    """Move overdue, not-yet-submitted work to ``pending``."""
    when = now or utcnow()
    conn.execute(
        "UPDATE assignments SET status = 'pending'"
        f" WHERE due_date IS NOT NULL AND due_date < ? AND status IN ({PRE_SUBMIT_LIST})",
        (when, *PRE_SUBMIT_STATUSES),
    )


def resolve_status(
    current: str, due_date: str | None, opened: bool, now: str | None = None
) -> str:
    """The canonical status for an assignment still in the student's hands.

    One rule covers everything the student can still act on: past due and not
    submitted means ``pending``; otherwise ``in_progress`` once they have
    opened it and ``assigned`` until then. ``submitted`` and ``completed``
    belong to the trainer and pass through untouched.
    """
    if current in ("submitted", "completed"):
        return current
    if due_date and due_date < (now or utcnow()):
        return "pending"
    return "in_progress" if opened else "assigned"


def migrate_assignment_statuses(conn: sqlite3.Connection) -> None:
    """One-time remap from legacy assignment status values."""
    key = "assignment_status_v2"
    if conn.execute("SELECT 1 FROM migrations WHERE key = ?", (key,)).fetchone():
        return
    # "approved" was the old terminal state. Everything else that is not one
    # of the five canonical values ("changes_requested", "open", anything a
    # forgotten editor wrote) folds back through the canonical rule above.
    conn.execute("UPDATE assignments SET status = 'completed' WHERE status = 'approved'")
    conn.execute(
        "UPDATE assignments SET status = CASE"
        " WHEN due_date IS NOT NULL AND due_date < ? THEN 'pending'"
        " WHEN last_opened_at IS NOT NULL THEN 'in_progress'"
        " ELSE 'assigned' END"
        " WHERE status NOT IN ('assigned', 'in_progress', 'submitted', 'pending', 'completed')",
        (utcnow(),),
    )
    sync_overdue_assignments(conn)
    conn.execute("INSERT INTO migrations (key, applied_at) VALUES (?, ?)", (key, utcnow()))

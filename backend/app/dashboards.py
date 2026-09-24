"""Dashboard aggregation for both portals (SRS §2, §3, §16, §17).

Read-only: every figure a dashboard shows is computed here from the platform
tables, so the two pages never have to agree on how a count is derived.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from .assignment_status import (
    ACTIVE_LIST,
    ACTIVE_STATUSES,
    PRE_SUBMIT_LIST,
    PRE_SUBMIT_STATUSES,
    sync_overdue_assignments,
)
from .db import ACTIVITY_CATEGORIES as _CATEGORIES, get_conn, utcnow
from .deps import get_current_user, require_student, require_trainer
from .names import display_name

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# How recently a student must have been seen for the roster to call them
# online. Long enough that reading a page does not flicker them offline.
PRESENCE_WINDOW_MIN = 5

# The dashboards page their activity feed fifteen at a time: enough that a busy
# week is one or two pages, few enough that a page scrolls rather than runs off.
ACTIVITY_PAGE = 15

# The filter's accepted values: one per category, plus "all".
ACTIVITY_CATEGORIES = ("all", *_CATEGORIES)

# Who did this to you, and in what capacity. A student needs to see that the
# warning on their exercise came from their trainer and not from the system.
ACTIVITY_SELECT = """
    SELECT a.id, a.kind, a.category, a.summary, a.link, a.created_at, a.actor_id,
           u.role AS actor_role, u.full_name AS actor_full_name,
           u.first_name AS actor_first_name, u.last_name AS actor_last_name,
           u.email AS actor_email
    FROM activities a
    LEFT JOIN users u ON u.id = a.actor_id
    WHERE a.user_id = ? AND (? = 'all' OR a.category = ?)
    ORDER BY a.created_at DESC, a.id DESC
"""

ACTIVITY_COUNT = (
    "SELECT COUNT(*) FROM activities"
    " WHERE user_id = ? AND (? = 'all' OR category = ?)"
)

# One row per assignment: its most recent submission, or NULLs if never submitted.
LATEST_SUBMISSION = """
    LEFT JOIN submissions s ON s.id = (
        SELECT id FROM submissions
        WHERE assignment_id = a.id
        ORDER BY submitted_at DESC, id DESC
        LIMIT 1
    )
"""


def _rows(cursor) -> list[dict]:
    return [dict(row) for row in cursor.fetchall()]


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _with_actor(rows: list[dict], viewer_id: int) -> list[dict]:
    """Attach who each activity came from, in a form the feed can label.

    `actor` is left empty for anything the reader did themselves -- "you
    submitted X" needs no attribution -- and for rows whose actor account is
    gone. `actor_role` is what lets the feed print "Nishanth (trainer)".
    """
    out = []
    for row in rows:
        actor_id = row.pop("actor_id", None)
        role = row.pop("actor_role", None) or ""
        name = display_name(
            {
                "full_name": row.pop("actor_full_name", "") or "",
                "first_name": row.pop("actor_first_name", "") or "",
                "last_name": row.pop("actor_last_name", "") or "",
                "email": row.pop("actor_email", "") or "",
            }
        ) if actor_id else ""
        mine = actor_id is not None and int(actor_id) == viewer_id
        row["actor"] = "" if mine else name
        row["actor_role"] = "" if mine else role
        out.append(row)
    return out


def _display(row: dict, name_key: str, email_key: str = "email") -> str:
    """`display_name` for a joined row that carries only a name and an email."""
    return display_name(
        {
            "full_name": row.get(name_key) or "",
            "first_name": "",
            "last_name": "",
            "email": row.get(email_key) or "",
        }
    )


def _notifications(conn: sqlite3.Connection, user_id: int) -> tuple[list[dict], int]:
    """Every unread notification, newest first, then recent read ones.

    Nothing unread is ever cut off behind a "more" line. When few are unread
    the list is topped up to five with the newest read ones.
    """
    unread = _scalar(
        conn,
        "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL",
        (user_id,),
    )
    rows = _rows(
        conn.execute(
            "SELECT id, kind, title, link, created_at, read_at FROM notifications"
            " WHERE user_id = ? ORDER BY read_at IS NOT NULL, created_at DESC, id DESC"
            " LIMIT ?",
            (user_id, max(unread, 5)),
        )
    )
    return rows, unread


def _feed(conn: sqlite3.Connection, user_id: int) -> dict:
    """Notifications and recent activity - shared by both dashboards (§17).

    The bell shows every unread notification (see `_notifications`).

    `activity` is the first page only. The dashboards page through the rest
    against /api/dashboard/activity, which is the same feed with an offset.
    """
    notifications, unread = _notifications(conn, user_id)
    activity = _with_actor(
        _rows(
            conn.execute(
                ACTIVITY_SELECT + " LIMIT ?", (user_id, "all", "all", ACTIVITY_PAGE)
            )
        ),
        user_id,
    )
    return {
        "notifications": notifications,
        "unread": unread,
        "activity": activity,
        "activity_total": _scalar(conn, ACTIVITY_COUNT, (user_id, "all", "all")),
    }


@router.get("/notifications")
def get_notifications(user: sqlite3.Row = Depends(get_current_user)) -> dict:
    user_id = int(user["id"])
    with get_conn() as conn:
        notifications, unread = _notifications(conn, user_id)
        return {"notifications": notifications, "unread": unread}


@router.get("/trainer")
def trainer_dashboard(user: sqlite3.Row = Depends(require_trainer)) -> dict:
    """Everything the trainer overview shows (SRS §2)."""
    trainer_id = int(user["id"])
    now = utcnow()

    with get_conn() as conn:
        sync_overdue_assignments(conn, now)
        stats = {
            "students": _scalar(
                conn, "SELECT COUNT(*) FROM users WHERE role = 'student' AND is_active = 1"
            ),
            "exercises": _scalar(
                conn, "SELECT COUNT(*) FROM exercises WHERE trainer_id = ?", (trainer_id,)
            ),
            "published": _scalar(
                conn,
                "SELECT COUNT(*) FROM exercises WHERE trainer_id = ? AND status = 'published'",
                (trainer_id,),
            ),
            "drafts": _scalar(
                conn,
                "SELECT COUNT(*) FROM exercises WHERE trainer_id = ? AND status = 'draft'",
                (trainer_id,),
            ),
            # Everything not yet submitted -- assigned, in progress or past
            # due. ``overdue`` below is the past-due slice of this figure.
            "pending": _scalar(
                conn,
                "SELECT COUNT(*) FROM assignments a JOIN exercises e ON e.id = a.exercise_id"
                f" WHERE e.trainer_id = ? AND a.status IN ({ACTIVE_LIST})",
                (trainer_id, *ACTIVE_STATUSES),
            ),
            "awaiting_review": _scalar(
                conn,
                "SELECT COUNT(*) FROM submissions s JOIN exercises e ON e.id = s.exercise_id"
                " WHERE e.trainer_id = ? AND s.review_status = 'pending'",
                (trainer_id,),
            ),
            "completed": _scalar(
                conn,
                "SELECT COUNT(*) FROM assignments a JOIN exercises e ON e.id = a.exercise_id"
                " WHERE e.trainer_id = ? AND a.status = 'completed'",
                (trainer_id,),
            ),
            "overdue": _scalar(
                conn,
                "SELECT COUNT(*) FROM assignments a JOIN exercises e ON e.id = a.exercise_id"
                " WHERE e.trainer_id = ? AND a.status = 'pending'",
                (trainer_id,),
            ),
            # Queries students raised on pending exercises and are waiting on
            # the trainer. The Query raised card links to the page that answers
            # them; the answered ones are that page's history.
            "new_queries": _scalar(
                conn,
                "SELECT COUNT(*) FROM access_requests WHERE trainer_id = ? AND status = 'pending'",
                (trainer_id,),
            ),
        }

        review_queue = _rows(
            conn.execute(
                "SELECT s.id, s.assignment_id, s.submitted_at, s.result, s.tests_passed,"
                "       s.tests_total, s.code, s.student_id,"
                "       u.full_name AS student, u.email AS student_email,"
                "       e.title AS exercise, e.id AS exercise_id"
                " FROM submissions s"
                " JOIN exercises e ON e.id = s.exercise_id"
                " JOIN users u ON u.id = s.student_id"
                " WHERE e.trainer_id = ? AND s.review_status = 'pending'"
                " ORDER BY s.submitted_at ASC, s.id ASC",
                (trainer_id,),
            )
        )
        for row in review_queue:
            row["display"] = _display(row, "student", "student_email")

        pending = _rows(
            conn.execute(
                "SELECT a.id, a.status, a.due_date, a.last_opened_at,"
                "       u.full_name AS student, u.email AS student_email,"
                "       e.title AS exercise, e.id AS exercise_id"
                " FROM assignments a"
                " JOIN exercises e ON e.id = a.exercise_id"
                " JOIN users u ON u.id = a.student_id"
                f" WHERE e.trainer_id = ? AND a.status IN ({ACTIVE_LIST})"
                " ORDER BY a.due_date IS NULL, a.due_date ASC",
                (trainer_id, *ACTIVE_STATUSES),
            )
        )
        for row in pending:
            row["overdue"] = bool(row["due_date"] and row["due_date"] < now)
            row["display"] = _display(row, "student", "student_email")

        completed_rows = _rows(
            conn.execute(
                "SELECT a.id, a.status, a.due_date,"
                "       u.id AS student_id, u.full_name AS student, u.email AS student_email,"
                "       e.title AS exercise,"
                "       s.submitted_at, s.tests_passed, s.tests_total"
                " FROM assignments a"
                " JOIN exercises e ON e.id = a.exercise_id"
                " JOIN users u ON u.id = a.student_id"
                f"{LATEST_SUBMISSION}"
                " WHERE e.trainer_id = ? AND a.status = 'completed'"
                " ORDER BY s.submitted_at DESC",
                (trainer_id,),
            )
        )
        for row in completed_rows:
            row["display"] = _display(row, "student", "student_email")

        students = _rows(
            conn.execute(
                "SELECT u.id, u.full_name AS name, u.email, u.is_active, u.last_seen_at,"
                "       COUNT(a.id) AS assigned,"
                "       SUM(CASE WHEN a.status = 'completed' THEN 1 ELSE 0 END) AS completed,"
                f"      SUM(CASE WHEN a.status IN ({ACTIVE_LIST}) THEN 1 ELSE 0 END) AS pending,"
                "       SUM(CASE WHEN a.status = 'submitted' THEN 1 ELSE 0 END) AS awaiting"
                " FROM users u"
                " LEFT JOIN assignments a ON a.student_id = u.id"
                "   AND a.exercise_id IN (SELECT id FROM exercises WHERE trainer_id = ?)"
                " WHERE u.role = 'student'"
                " GROUP BY u.id ORDER BY u.full_name COLLATE NOCASE",
                (*ACTIVE_STATUSES, trainer_id),
            )
        )
        online_after = (
            datetime.now(timezone.utc) - timedelta(minutes=PRESENCE_WINDOW_MIN)
        ).isoformat(timespec="seconds")
        for row in students:
            row["progress"] = (
                round(100 * row["completed"] / row["assigned"]) if row["assigned"] else 0
            )
            row["display"] = _display(row, "name", "email")
            row["online"] = bool(row["last_seen_at"] and row["last_seen_at"] >= online_after)

        exercises = _rows(
            conn.execute(
                "SELECT e.id, e.title, e.status, e.due_date, e.updated_at,"
                "       COUNT(a.id) AS assigned,"
                "       (SELECT COUNT(*) FROM test_cases t WHERE t.exercise_id = e.id) AS tests"
                " FROM exercises e"
                " LEFT JOIN assignments a ON a.exercise_id = e.id"
                " WHERE e.trainer_id = ?"
                " GROUP BY e.id ORDER BY e.updated_at DESC",
                (trainer_id,),
            )
        )

        queries = _rows(
            conn.execute(
                "SELECT q.*, e.title AS exercise, u.full_name AS student, u.email"
                " FROM queries q"
                " JOIN assignments a ON a.id = q.assignment_id"
                " JOIN exercises e ON e.id = a.exercise_id"
                " JOIN users u ON u.id = q.student_id"
                " WHERE q.trainer_id = ? ORDER BY q.created_at DESC LIMIT 50",
                (trainer_id,),
            )
        )
        for row in queries:
            row["display"] = _display(row, "student", "email")

        # What is due next across this trainer's class, one row per exercise
        # rather than one per student -- the trainer wants the deadline, not
        # thirty copies of it.
        deadlines = _rows(
            conn.execute(
                "SELECT e.id, e.title, a.due_date,"
                "       COUNT(*) AS assigned,"
                f"      SUM(CASE WHEN a.status IN ({PRE_SUBMIT_LIST}) THEN 1 ELSE 0 END) AS outstanding"
                " FROM assignments a JOIN exercises e ON e.id = a.exercise_id"
                " WHERE e.trainer_id = ? AND a.due_date IS NOT NULL"
                f"   AND a.status IN ({PRE_SUBMIT_LIST})"
                " GROUP BY e.id, a.due_date"
                " ORDER BY a.due_date ASC",
                (*PRE_SUBMIT_STATUSES, trainer_id, *PRE_SUBMIT_STATUSES),
            )
        )
        for row in deadlines:
            row["overdue"] = bool(row["due_date"] and row["due_date"] < now)

        feed = _feed(conn, trainer_id)

    return {
        "user": {"name": display_name(user), "email": user["email"]},
        "stats": stats,
        "deadlines": deadlines,
        "queries": queries,
        "review_queue": review_queue,
        "pending": pending,
        "completed": completed_rows,
        "students": students,
        "exercises": exercises,
        "now": now,
        **feed,
    }


@router.get("/trainer/overdue-exercises")
def overdue_exercises(user: sqlite3.Row = Depends(require_trainer)) -> dict:
    """Overdue exercises grouped by exercise, each with the list of students
    who have not yet completed/submitted (for the Pending Submissions page)."""
    trainer_id = int(user["id"])
    now = utcnow()
    with get_conn() as conn:
        sync_overdue_assignments(conn, now)
        rows = _rows(
            conn.execute(
                "SELECT e.id AS exercise_id, e.title, e.due_date,"
                "       u.id AS student_id, u.full_name AS student, u.email AS student_email,"
                "       a.status, a.last_opened_at"
                " FROM assignments a"
                " JOIN exercises e ON e.id = a.exercise_id"
                " JOIN users u ON u.id = a.student_id"
                " WHERE e.trainer_id = ? AND a.status = 'pending'"
                " ORDER BY e.due_date ASC, e.title COLLATE NOCASE, u.full_name COLLATE NOCASE",
                (trainer_id,),
            )
        )

        # Group into exercises → list of students
        exercises: dict[int, dict] = {}
        for r in rows:
            eid = r["exercise_id"]
            if eid not in exercises:
                exercises[eid] = {
                    "exercise_id": eid,
                    "title": r["title"],
                    "due_date": r["due_date"],
                    "students": [],
                }
            exercises[eid]["students"].append(
                {
                    "student_id": r["student_id"],
                    "display": _display(r, "student", "student_email"),
                    "status": r["status"],
                    "last_opened_at": r["last_opened_at"],
                }
            )

    return {"exercises": list(exercises.values()), "total": len(exercises)}



@router.get("/student")
def student_dashboard(user: sqlite3.Row = Depends(require_student)) -> dict:
    """Everything the student overview shows (SRS §3)."""
    student_id = int(user["id"])
    now = utcnow()

    with get_conn() as conn:
        sync_overdue_assignments(conn, now)
        assignments = _rows(
            conn.execute(
                "SELECT a.id, a.status, a.due_date, a.assigned_at, a.last_opened_at,"
                "       a.notebook_id, e.id AS exercise_id, e.title, e.problem_statement,"
                "       s.id AS submission_id, s.result, s.tests_passed, s.tests_total,"
                "       s.review_status, s.comment, s.submitted_at, s.reviewed_at,"
                "       t.full_name AS trainer, t.email AS trainer_email"
                " FROM assignments a"
                " JOIN exercises e ON e.id = a.exercise_id"
                " JOIN users t ON t.id = e.trainer_id"
                f"{LATEST_SUBMISSION}"
                " WHERE a.student_id = ? AND e.status = 'published'"
                " ORDER BY a.due_date IS NULL, a.due_date ASC, a.assigned_at DESC",
                (student_id,),
            )
        )
        for row in assignments:
            row["overdue"] = row["status"] == "pending"
            # Trim the statement down to a dashboard-sized preview.
            statement = (row.pop("problem_statement") or "").strip()
            row["preview"] = statement[:180] + ("..." if len(statement) > 180 else "")
            # A trainer's full_name is often empty (SRS: never show a raw email).
            row["trainer"] = _display(row, "trainer", "trainer_email")

        stats = {
            "assigned": sum(1 for a in assignments if a["status"] == "assigned"),
            "in_progress": sum(1 for a in assignments if a["status"] == "in_progress"),
            "submitted": sum(1 for a in assignments if a["status"] == "submitted"),
            "pending": sum(1 for a in assignments if a["status"] == "pending"),
            "completed": sum(1 for a in assignments if a["status"] == "completed"),
            "overdue": sum(1 for a in assignments if a["status"] == "pending"),
        }

        # "Continue where you left off" (§3): the most recently opened piece of
        # open work, falling back to whatever is due soonest.
        open_work = [a for a in assignments if a["status"] in ACTIVE_STATUSES]
        resume = None
        if open_work:
            opened = [a for a in open_work if a["last_opened_at"]]
            resume = max(opened, key=lambda a: a["last_opened_at"]) if opened else open_work[0]

        queries = _rows(
            conn.execute(
                "SELECT q.*, e.title AS exercise"
                " FROM queries q"
                " JOIN assignments a ON a.id = q.assignment_id"
                " JOIN exercises e ON e.id = a.exercise_id"
                " WHERE q.student_id = ? ORDER BY q.created_at DESC LIMIT 50",
                (student_id,),
            )
        )

        feed = _feed(conn, student_id)

    return {
        "user": {"name": display_name(user), "email": user["email"]},
        "stats": stats,
        "queries": queries,
        "assignments": assignments,
        "resume": resume,
        "now": now,
        **feed,
    }


@router.post("/notifications/read")
def mark_notifications_read(user: sqlite3.Row = Depends(get_current_user)) -> dict:
    """Clear the bell (SRS §17)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL",
            (utcnow(), user["id"]),
        )
    return {"ok": True}


@router.get("/activity")
def full_activity(
    limit: int = Query(ACTIVITY_PAGE, ge=1, le=200),
    offset: int = Query(0, ge=0),
    category: str = Query("all"),
    user: sqlite3.Row = Depends(get_current_user),
) -> dict:
    """One page of the signed-in account's activity, newest first.

    Both dashboards show fifteen at a time and step through with Next, so the
    total travels with the page; the history page asks for a large limit and
    searches what it gets client-side.

    ``category`` narrows the feed to one kind of thing -- exercises, modules or
    submissions. It is applied here rather than over the page the browser
    already holds: filtering fifteen rows client-side hides everything older
    than those fifteen and leaves the pager counting the wrong total.
    """
    if category not in ACTIVITY_CATEGORIES:
        category = "all"
    with get_conn() as conn:
        items = _with_actor(
            _rows(
                conn.execute(
                    ACTIVITY_SELECT + " LIMIT ? OFFSET ?",
                    (user["id"], category, category, limit, offset),
                )
            ),
            int(user["id"]),
        )
        total = _scalar(conn, ACTIVITY_COUNT, (user["id"], category, category))
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "category": category,
    }

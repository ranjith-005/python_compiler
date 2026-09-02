"""Dashboard aggregation for both portals (SRS §2, §3, §16, §17).

Read-only: every figure a dashboard shows is computed here from the platform
tables, so the two pages never have to agree on how a count is derived.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from .db import get_conn, utcnow
from .deps import get_current_user, require_student, require_trainer
from .names import display_name

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# Statuses that mean "the student still owes work on this assignment".
OPEN_STATUSES = ("assigned", "in_progress", "changes_requested")
OPEN_LIST = ",".join("?" * len(OPEN_STATUSES))

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


def _feed(conn: sqlite3.Connection, user_id: int) -> dict:
    """Notifications and recent activity - shared by both dashboards (§17)."""
    notifications = _rows(
        conn.execute(
            "SELECT id, kind, title, link, created_at, read_at FROM notifications"
            " WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 12",
            (user_id,),
        )
    )
    activity = _rows(
        conn.execute(
            "SELECT id, kind, summary, link, created_at FROM activities"
            " WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 12",
            (user_id,),
        )
    )
    return {
        "notifications": notifications,
        "unread": sum(1 for n in notifications if not n["read_at"]),
        "activity": activity,
    }


@router.get("/trainer")
def trainer_dashboard(user: sqlite3.Row = Depends(require_trainer)) -> dict:
    """Everything the trainer overview shows (SRS §2)."""
    trainer_id = int(user["id"])
    now = utcnow()

    with get_conn() as conn:
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
            "pending": _scalar(
                conn,
                "SELECT COUNT(*) FROM assignments a JOIN exercises e ON e.id = a.exercise_id"
                f" WHERE e.trainer_id = ? AND a.status IN ({OPEN_LIST})",
                (trainer_id, *OPEN_STATUSES),
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
                f" WHERE e.trainer_id = ? AND a.status IN ({OPEN_LIST})"
                " AND a.due_date IS NOT NULL AND a.due_date < ?",
                (trainer_id, *OPEN_STATUSES, now),
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
                "       e.title AS exercise"
                " FROM assignments a"
                " JOIN exercises e ON e.id = a.exercise_id"
                " JOIN users u ON u.id = a.student_id"
                f" WHERE e.trainer_id = ? AND a.status IN ({OPEN_LIST})"
                " ORDER BY a.due_date IS NULL, a.due_date ASC",
                (trainer_id, *OPEN_STATUSES),
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
                "SELECT u.id, u.full_name AS name, u.email, u.is_active,"
                "       COUNT(a.id) AS assigned,"
                "       SUM(CASE WHEN a.status = 'completed' THEN 1 ELSE 0 END) AS completed,"
                f"      SUM(CASE WHEN a.status IN ({OPEN_LIST}) THEN 1 ELSE 0 END) AS pending,"
                "       SUM(CASE WHEN a.status = 'submitted' THEN 1 ELSE 0 END) AS awaiting"
                " FROM users u"
                " LEFT JOIN assignments a ON a.student_id = u.id"
                "   AND a.exercise_id IN (SELECT id FROM exercises WHERE trainer_id = ?)"
                " WHERE u.role = 'student'"
                " GROUP BY u.id ORDER BY u.full_name COLLATE NOCASE",
                (*OPEN_STATUSES, trainer_id),
            )
        )
        for row in students:
            row["progress"] = (
                round(100 * row["completed"] / row["assigned"]) if row["assigned"] else 0
            )
            row["display"] = _display(row, "name", "email")

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

        feed = _feed(conn, trainer_id)

    return {
        "user": {"name": display_name(user), "email": user["email"]},
        "stats": stats,
        "queries": queries,
        "review_queue": review_queue,
        "pending": pending,
        "completed": completed_rows,
        "students": students,
        "exercises": exercises,
        "now": now,
        **feed,
    }


@router.get("/student")
def student_dashboard(user: sqlite3.Row = Depends(require_student)) -> dict:
    """Everything the student overview shows (SRS §3)."""
    student_id = int(user["id"])
    now = utcnow()

    with get_conn() as conn:
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
            row["overdue"] = bool(
                row["due_date"] and row["due_date"] < now and row["status"] in OPEN_STATUSES
            )
            # Trim the statement down to a dashboard-sized preview.
            statement = (row.pop("problem_statement") or "").strip()
            row["preview"] = statement[:180] + ("..." if len(statement) > 180 else "")
            # A trainer's full_name is often empty (SRS: never show a raw email).
            row["trainer"] = _display(row, "trainer", "trainer_email")

        stats = {
            "assigned": len(assignments),
            "in_progress": sum(1 for a in assignments if a["status"] == "in_progress"),
            "submitted": sum(1 for a in assignments if a["status"] == "submitted"),
            "changes_requested": sum(
                1 for a in assignments if a["status"] == "changes_requested"
            ),
            "completed": sum(
                1 for a in assignments if a["status"] in ("approved", "completed")
            ),
            "overdue": sum(1 for a in assignments if a["overdue"]),
        }

        # "Continue where you left off" (§3): the most recently opened piece of
        # open work, falling back to whatever is due soonest.
        open_work = [a for a in assignments if a["status"] in OPEN_STATUSES]
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
def full_activity(user: sqlite3.Row = Depends(get_current_user)) -> list[dict]:
    with get_conn() as conn:
        return _rows(conn.execute("SELECT id, kind, summary, link, created_at FROM activities WHERE user_id = ? ORDER BY created_at DESC, id DESC", (user["id"],)))

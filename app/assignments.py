"""Exercises, assignments, submissions and review (SRS §5, §6, §10-§14).

These are the writes the two dashboards drive: a trainer creates an exercise
and assigns it, a student opens it (which gives them a notebook to work in) and
submits, and the trainer reviews what comes back. Every one of them moves a
number on a dashboard, so they live next to the aggregation in dashboards.py.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from .config import settings
from .db import create_notebook, get_conn, notify, record_activity, utcnow
from .deps import get_current_user, require_student, require_trainer
from .schemas import ExerciseIn, ReviewIn
from .workspace import workspace_dir

router = APIRouter(prefix="/api", tags=["assignments"])

# A submitted solution is run once per test case; keep each run short so a
# runaway loop in a student's code cannot tie up a request.
RUN_TIMEOUT_SEC = min(settings.CELL_TIMEOUT_SEC, 15)


def _due(value: str | None) -> str | None:
    """Accept a date or datetime from the form and store it as UTC ISO."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _exercise_cells(row: sqlite3.Row, tests: list[sqlite3.Row]) -> list[tuple[str, str]]:
    """The notebook a student gets when they open an assignment (SRS §7, §8)."""
    parts = [f"## {row['title']}", "", row["problem_statement"] or ""]
    for label, key in (
        ("Input format", "input_format"),
        ("Output format", "output_format"),
        ("Constraints", "constraints"),
        ("Explanation", "explanation"),
    ):
        if row[key]:
            parts += ["", f"**{label}**", "", row[key]]
    if row["sample_input"] or row["sample_output"]:
        parts += [
            "",
            "**Sample input**",
            "",
            "```\n" + (row["sample_input"] or "") + "\n```",
            "",
            "**Sample output**",
            "",
            "```\n" + (row["sample_output"] or "") + "\n```",
        ]
    public = [t for t in tests if not t["is_hidden"]]
    if public:
        parts += ["", f"**Public test cases:** {len(public)}"]
    if row["due_date"]:
        parts += ["", f"_Due {row['due_date']}_"]

    starter = row["starter_code"] or "# Write your solution here.\n"
    return [("markdown", "\n".join(parts)), ("code", starter)]


def _notebook_code(conn: sqlite3.Connection, notebook_id: int) -> str:
    """The student's solution: every code cell in their assignment notebook."""
    rows = conn.execute(
        "SELECT source FROM cells WHERE notebook_id = ? AND cell_type = 'code'"
        " ORDER BY position",
        (notebook_id,),
    ).fetchall()
    return "\n\n".join(r["source"] for r in rows if r["source"].strip())


def _evaluate(code: str, tests: list[sqlite3.Row], cwd) -> dict:
    """Run one solution against every test case (SRS §10, §12).

    Same trust boundary as the notebook kernel: this executes the student's own
    code as a normal process. See the security note in the README.
    """
    if not code.strip():
        return {"result": "wrong_answer", "passed": 0, "total": len(tests), "detail": "Empty solution."}
    try:
        compile(code, "<solution>", "exec")
    except SyntaxError as exc:
        return {
            "result": "syntax_error",
            "passed": 0,
            "total": len(tests),
            "detail": f"{exc.msg} (line {exc.lineno})",
        }

    passed = 0
    detail = ""
    for test in tests:
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                input=test["stdin"],
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT_SEC,
                cwd=str(cwd),
            )
        except subprocess.TimeoutExpired:
            return {
                "result": "runtime_error",
                "passed": passed,
                "total": len(tests),
                "detail": f"Timed out after {RUN_TIMEOUT_SEC}s.",
            }
        if proc.returncode != 0:
            return {
                "result": "runtime_error",
                "passed": passed,
                "total": len(tests),
                "detail": (proc.stderr or "").strip()[-400:],
            }
        if proc.stdout.strip() == (test["expected_output"] or "").strip():
            passed += 1
        elif not detail:
            detail = "Output did not match the expected result."

    result = "accepted" if passed == len(tests) and tests else "wrong_answer"
    return {"result": result, "passed": passed, "total": len(tests), "detail": detail}


# ─────────────────────────────── trainer side ───────────────────────────────


@router.get("/students")
def list_students(user: sqlite3.Row = Depends(require_trainer)) -> list[dict]:
    """Everyone a trainer can assign work to (SRS §4)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, email, full_name AS name, is_active, created_at FROM users"
            " WHERE role = 'student' ORDER BY full_name COLLATE NOCASE"
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/exercises", status_code=status.HTTP_201_CREATED)
def create_exercise(body: ExerciseIn, user: sqlite3.Row = Depends(require_trainer)) -> dict:
    """Create an exercise with its test cases and assign it (SRS §5, §6, §10)."""
    now = utcnow()
    due = _due(body.due_date)
    trainer_id = int(user["id"])

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO exercises (trainer_id, title, problem_statement, input_format,"
            " output_format, sample_input, sample_output, explanation, constraints,"
            " starter_code, due_date, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                trainer_id,
                body.title.strip(),
                body.problem_statement,
                body.input_format,
                body.output_format,
                body.sample_input,
                body.sample_output,
                body.explanation,
                body.constraints,
                body.starter_code,
                due,
                body.status,
                now,
                now,
            ),
        )
        exercise_id = int(cur.lastrowid)

        for position, test in enumerate(body.test_cases):
            conn.execute(
                "INSERT INTO test_cases (exercise_id, position, stdin, expected_output, is_hidden)"
                " VALUES (?, ?, ?, ?, ?)",
                (exercise_id, position, test.stdin, test.expected_output, int(test.is_hidden)),
            )

        assigned = 0
        if body.assign_to and body.status == "published":
            valid = {
                int(r["id"])
                for r in conn.execute(
                    "SELECT id FROM users WHERE role = 'student' AND is_active = 1"
                ).fetchall()
            }
            for student_id in dict.fromkeys(body.assign_to):
                if int(student_id) not in valid:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO assignments (exercise_id, student_id, assigned_by,"
                    " assigned_at, due_date, status) VALUES (?, ?, ?, ?, ?, 'assigned')",
                    (exercise_id, student_id, trainer_id, now, due),
                )
                assigned += 1
                notify(
                    conn,
                    student_id,
                    "assigned",
                    f"New exercise assigned: {body.title.strip()}",
                    "/student",
                )
                record_activity(
                    conn,
                    student_id,
                    "assigned",
                    f"{user['full_name'] or user['email']} assigned \"{body.title.strip()}\"",
                    trainer_id,
                    "/student",
                )

        record_activity(
            conn,
            trainer_id,
            "created",
            f"Created \"{body.title.strip()}\" and assigned it to {assigned} student(s)",
            trainer_id,
            "/trainer",
        )

    return {"id": exercise_id, "assigned": assigned}


@router.post("/submissions/{submission_id}/review")
def review_submission(
    submission_id: int, body: ReviewIn, user: sqlite3.Row = Depends(require_trainer)
) -> dict:
    """Approve, request changes, or mark complete (SRS §13, §14)."""
    now = utcnow()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT s.id, s.assignment_id, s.student_id, e.title, e.trainer_id"
            " FROM submissions s JOIN exercises e ON e.id = s.exercise_id"
            " WHERE s.id = ?",
            (submission_id,),
        ).fetchone()
        if row is None or int(row["trainer_id"]) != int(user["id"]):
            raise HTTPException(status_code=404, detail="Submission not found.")

        review_status = "changes_requested" if body.action == "request_changes" else "approved"
        assignment_status = {
            "approve": "approved",
            "complete": "completed",
            "request_changes": "changes_requested",
        }[body.action]

        conn.execute(
            "UPDATE submissions SET review_status = ?, comment = ?, reviewed_at = ?,"
            " reviewed_by = ? WHERE id = ?",
            (review_status, body.comment, now, user["id"], submission_id),
        )
        conn.execute(
            "UPDATE assignments SET status = ? WHERE id = ?",
            (assignment_status, row["assignment_id"]),
        )

        headline = {
            "approve": f"Solution approved: {row['title']}",
            "complete": f"Exercise marked complete: {row['title']}",
            "request_changes": f"Changes requested: {row['title']}",
        }[body.action]
        notify(conn, int(row["student_id"]), body.action, headline, "/student")
        record_activity(conn, int(row["student_id"]), body.action, headline, int(user["id"]), "/student")
        record_activity(
            conn,
            int(user["id"]),
            "reviewed",
            f"Reviewed a submission for \"{row['title']}\"",
            int(user["id"]),
            "/trainer",
        )

    return {"ok": True, "review_status": review_status, "assignment_status": assignment_status}


# ─────────────────────────────── student side ───────────────────────────────


def _load_assignment(conn: sqlite3.Connection, assignment_id: int, student_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT a.*, e.title, e.trainer_id, e.problem_statement, e.input_format,"
        "       e.output_format, e.sample_input, e.sample_output, e.explanation,"
        "       e.constraints, e.starter_code, e.due_date AS exercise_due"
        " FROM assignments a JOIN exercises e ON e.id = a.exercise_id"
        " WHERE a.id = ? AND a.student_id = ?",
        (assignment_id, student_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Assignment not found.")
    return row


@router.post("/assignments/{assignment_id}/open")
def open_assignment(assignment_id: int, user: sqlite3.Row = Depends(require_student)) -> dict:
    """Open the exercise, creating the working notebook on first visit (SRS §3, §8)."""
    student_id = int(user["id"])
    now = utcnow()
    with get_conn() as conn:
        row = _load_assignment(conn, assignment_id, student_id)
        notebook_id = row["notebook_id"]

        # A deleted notebook should not strand the assignment - recreate it.
        if notebook_id is not None:
            exists = conn.execute(
                "SELECT 1 FROM notebooks WHERE id = ? AND user_id = ?",
                (notebook_id, student_id),
            ).fetchone()
            if not exists:
                notebook_id = None

        if notebook_id is None:
            tests = conn.execute(
                "SELECT stdin, expected_output, is_hidden FROM test_cases"
                " WHERE exercise_id = ? ORDER BY position",
                (row["exercise_id"],),
            ).fetchall()
            notebook_id = create_notebook(
                conn, student_id, f"{row['title']}.ipynb", _exercise_cells(row, tests)
            )

        status_next = "in_progress" if row["status"] == "assigned" else row["status"]
        conn.execute(
            "UPDATE assignments SET notebook_id = ?, last_opened_at = ?, status = ? WHERE id = ?",
            (notebook_id, now, status_next, assignment_id),
        )

    return {"notebook_id": notebook_id, "status": status_next}


@router.post("/assignments/{assignment_id}/submit")
def submit_assignment(assignment_id: int, user: sqlite3.Row = Depends(require_student)) -> dict:
    """Submit the notebook's code and evaluate it automatically (SRS §11, §12)."""
    student_id = int(user["id"])
    now = utcnow()
    with get_conn() as conn:
        row = _load_assignment(conn, assignment_id, student_id)
        if row["status"] in ("approved", "completed"):
            raise HTTPException(status_code=409, detail="This exercise is already closed.")
        if row["notebook_id"] is None:
            raise HTTPException(status_code=409, detail="Open the exercise before submitting.")

        code = _notebook_code(conn, int(row["notebook_id"]))
        tests = conn.execute(
            "SELECT stdin, expected_output, is_hidden FROM test_cases"
            " WHERE exercise_id = ? ORDER BY position",
            (row["exercise_id"],),
        ).fetchall()

        # Hidden tests count towards the verdict but are never detailed back (§10).
        verdict = _evaluate(code, list(tests), workspace_dir(student_id))

        # A resubmission replaces the one waiting in the trainer's queue; the
        # earlier attempt stays in the history (SRS §15).
        conn.execute(
            "UPDATE submissions SET review_status = 'superseded'"
            " WHERE assignment_id = ? AND review_status = 'pending'",
            (assignment_id,),
        )
        cur = conn.execute(
            "INSERT INTO submissions (assignment_id, student_id, exercise_id, code,"
            " submitted_at, result, tests_total, tests_passed, review_status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            (
                assignment_id,
                student_id,
                row["exercise_id"],
                code,
                now,
                verdict["result"],
                verdict["total"],
                verdict["passed"],
            ),
        )
        conn.execute(
            "UPDATE assignments SET status = 'submitted' WHERE id = ?", (assignment_id,)
        )

        title = row["title"]
        notify(
            conn,
            int(row["trainer_id"]),
            "submitted",
            f"{user['full_name'] or user['email']} submitted \"{title}\"",
            "/trainer",
        )
        record_activity(
            conn,
            int(row["trainer_id"]),
            "submitted",
            f"{user['full_name'] or user['email']} submitted \"{title}\""
            f" - {verdict['passed']}/{verdict['total']} tests passed",
            student_id,
            "/trainer",
        )
        record_activity(
            conn,
            student_id,
            "submitted",
            f"Submitted \"{title}\" - {verdict['result'].replace('_', ' ')}",
            student_id,
            "/student",
        )

    return {"id": int(cur.lastrowid), **verdict}


@router.get("/assignments/{assignment_id}")
def assignment_detail(assignment_id: int, user: sqlite3.Row = Depends(get_current_user)) -> dict:
    """The assignment page payload (SRS §7): statement, samples, public tests, history."""
    with get_conn() as conn:
        if user["role"] == "student":
            row = _load_assignment(conn, assignment_id, int(user["id"]))
        else:
            row = conn.execute(
                "SELECT a.*, e.title, e.trainer_id, e.problem_statement, e.input_format,"
                "       e.output_format, e.sample_input, e.sample_output, e.explanation,"
                "       e.constraints, e.starter_code, e.due_date AS exercise_due"
                " FROM assignments a JOIN exercises e ON e.id = a.exercise_id"
                " WHERE a.id = ? AND e.trainer_id = ?",
                (assignment_id, user["id"]),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Assignment not found.")

        public_tests = [
            dict(r)
            for r in conn.execute(
                "SELECT stdin, expected_output FROM test_cases"
                " WHERE exercise_id = ? AND is_hidden = 0 ORDER BY position",
                (row["exercise_id"],),
            ).fetchall()
        ]
        hidden = conn.execute(
            "SELECT COUNT(*) FROM test_cases WHERE exercise_id = ? AND is_hidden = 1",
            (row["exercise_id"],),
        ).fetchone()[0]
        history = [
            dict(r)
            for r in conn.execute(
                "SELECT id, submitted_at, result, tests_passed, tests_total, review_status,"
                "       comment, reviewed_at FROM submissions"
                " WHERE assignment_id = ? ORDER BY submitted_at DESC, id DESC",
                (assignment_id,),
            ).fetchall()
        ]

    exercise = {
        key: row[key]
        for key in (
            "title",
            "problem_statement",
            "input_format",
            "output_format",
            "sample_input",
            "sample_output",
            "explanation",
            "constraints",
        )
    }
    return {
        "id": row["id"],
        "status": row["status"],
        "due_date": row["due_date"],
        "notebook_id": row["notebook_id"],
        "exercise": exercise,
        "public_tests": public_tests,
        "hidden_tests": hidden,
        "history": history,
    }

"""Exercises, assignments, submissions and review (SRS §5, §6, §10-§14).

These are the writes the two dashboards drive: a trainer creates an exercise
and assigns it, a student opens it and submits, and the trainer reviews what
comes back. Every one of them moves a number on a dashboard, so they live next
to the aggregation in dashboards.py.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .config import settings
from .dashboards import OPEN_STATUSES
from .db import get_conn, notify, record_activity, utcnow
from .deps import get_current_user, require_student, require_trainer
from .names import display_name
from .schemas import (
    AccessDecisionIn,
    AccessRequestIn,
    AssignIn,
    ExerciseIn,
    NewStudentIn,
    QueryIn,
    QueryReplyIn,
    ReviewIn,
    SolutionIn,
)
from .security import hash_password
from .workspace import workspace_dir

router = APIRouter(prefix="/api", tags=["assignments"])

# A submitted solution is run once per test case; keep each run short so a
# runaway loop in a student's code cannot tie up a request.
RUN_TIMEOUT_SEC = min(settings.CELL_TIMEOUT_SEC, 15)

# A runaway `while True: print(x)` can emit hundreds of megabytes inside the
# timeout. Truncate before it reaches memory-resident JSON; the student only
# needs enough output to see what their program did.
MAX_RUN_OUTPUT_CHARS = 64_000


def _clip(text: str) -> tuple[str, bool]:
    """Return the text capped for display, and whether it was cut."""
    if len(text) <= MAX_RUN_OUTPUT_CHARS:
        return text, False
    return text[:MAX_RUN_OUTPUT_CHARS], True


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
    failure_kind = ""
    cases: list[dict] = []

    # Every test runs, even after one fails. Stopping at the first failure
    # would report "1/3" without being able to say which two failed, and the
    # student needs the whole picture to know what to fix.
    for number, test in enumerate(tests, start=1):
        hidden = bool(test["is_hidden"])
        expected = (test["expected_output"] or "").strip()
        case = {"number": number, "hidden": hidden, "passed": False, "error": ""}
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                input=test["stdin"],
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT_SEC,
                cwd=str(cwd),
            )
            stdout, stderr, returncode = proc.stdout, proc.stderr, proc.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            stdout, stderr, returncode, timed_out = "", "", -1, True

        if timed_out:
            case["error"] = f"Timed out after {RUN_TIMEOUT_SEC}s."
            failure_kind = failure_kind or "runtime_error"
        elif returncode != 0:
            # The last line of a traceback is the exception and its message,
            # which is the part worth reading first.
            trace = (stderr or "").strip()
            case["error"] = trace.splitlines()[-1] if trace else "The program exited with an error."
            failure_kind = failure_kind or "runtime_error"
        elif stdout.strip() == expected:
            case["passed"] = True
            passed += 1
        else:
            case["error"] = "Output did not match the expected result."
            failure_kind = failure_kind or "wrong_answer"

        # A hidden case reports only whether it passed and why it did not. Its
        # input, its expected output and the student's actual output all stay
        # unpublished, or hiding it would have achieved nothing (SRS §10).
        if not hidden:
            case["stdin"] = test["stdin"] or ""
            case["expected"] = expected
            case["actual"] = (stdout or "").strip()
            if not timed_out and returncode != 0:
                case["error"] = (stderr or "").strip()[-800:] or case["error"]
        cases.append(case)
        if not case["passed"] and not detail:
            detail = case["error"]

    result = "accepted" if tests and passed == len(tests) else (failure_kind or "wrong_answer")
    return {
        "result": result,
        "passed": passed,
        "total": len(tests),
        "detail": detail,
        "cases": cases,
    }


# ─────────────────────────────── trainer side ───────────────────────────────


@router.get("/students")
def list_students(user: sqlite3.Row = Depends(require_trainer)) -> list[dict]:
    """Everyone a trainer can assign work to (SRS §4)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, email, full_name AS name, is_active, created_at FROM users"
            " WHERE role = 'student' ORDER BY full_name COLLATE NOCASE"
        ).fetchall()
    result = [dict(r) for r in rows]
    for row in result:
        row["display"] = _display(row, "name")
    return result


@router.post("/students", status_code=201)
def create_student(body: NewStudentIn, user: sqlite3.Row = Depends(require_trainer)) -> dict:
    """Create a student account and set its credentials.

    Students do not sign themselves up: the trainer enrols them and hands over
    the email and password, which is why the sign-in page offers no way to
    create an account.
    """
    email = str(body.email).strip()
    full_name = f"{body.first_name.strip()} {body.last_name.strip()}".strip()
    with get_conn() as conn:
        if conn.execute(
            "SELECT 1 FROM users WHERE email = ? COLLATE NOCASE", (email,)
        ).fetchone():
            raise HTTPException(status_code=409, detail="That email address is already in use.")
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, created_at, role, full_name,"
            " first_name, last_name, phone, is_active) VALUES (?, ?, ?, 'student', ?, ?, ?, ?, 1)",
            (email, hash_password(body.password), utcnow(), full_name,
             body.first_name.strip(), body.last_name.strip(), body.phone.strip()),
        )
        student_id = int(cur.lastrowid)
        record_activity(
            conn, int(user["id"]), "created",
            f'{display_name(user)} enrolled {full_name or email}',
            int(user["id"]), "/trainer/students",
        )
    return {"id": student_id, "email": email, "display": full_name or email}


@router.get("/exercises")
def list_exercises(
    status_filter: str | None = Query(None, alias="status"),
    user: sqlite3.Row = Depends(require_trainer),
) -> list[dict]:
    """Full trainer-owned exercise details, including assigned students.

    ``status=draft`` backs the drafts page (req 6).
    """
    where, params = "e.trainer_id = ?", [user["id"]]
    if status_filter in ("draft", "published"):
        where += " AND e.status = ?"
        params.append(status_filter)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT e.*, COUNT(a.id) AS assigned FROM exercises e LEFT JOIN assignments a ON a.exercise_id = e.id "
            f"WHERE {where} GROUP BY e.id ORDER BY e.updated_at DESC", params
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["students"] = [dict(s) for s in conn.execute(
                "SELECT u.id, u.full_name, u.email, a.status FROM assignments a JOIN users u ON u.id=a.student_id WHERE a.exercise_id=? ORDER BY u.full_name",
                (row["id"],),
            ).fetchall()]
            for s in item["students"]:
                s["display"] = _display(s, "full_name")
            result.append(item)
    return result


@router.delete("/exercises/{exercise_id}")
def delete_exercise(exercise_id: int, user: sqlite3.Row = Depends(require_trainer)) -> dict:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM exercises WHERE id = ? AND trainer_id = ?", (exercise_id, user["id"]))
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="Exercise not found.")
    return {"ok": True}


@router.put("/exercises/{exercise_id}")
def update_exercise(exercise_id: int, body: ExerciseIn, user: sqlite3.Row = Depends(require_trainer)) -> dict:
    """Alter an exercise while retaining existing student assignments."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE exercises SET title=?, problem_statement=?, input_format=?, output_format=?, sample_input=?, sample_output=?, explanation=?, constraints=?, starter_code=?, due_date=?, status=?, updated_at=? WHERE id=? AND trainer_id=?",
            (body.title.strip(), body.problem_statement, body.input_format, body.output_format, body.sample_input, body.sample_output, body.explanation, body.constraints, body.starter_code, _due(body.due_date), body.status, utcnow(), exercise_id, user["id"]),
        )
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="Exercise not found.")
    return {"ok": True, "id": exercise_id}


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
                    f"{display_name(user)} assigned \"{body.title.strip()}\"",
                    trainer_id,
                    "/student",
                )

        # Named, like every other line in the feed: the reference design's
        # activity list reads "<who> did <what>", and a trainer's own history
        # is the same feed a co-trainer would read.
        record_activity(
            conn,
            trainer_id,
            "created",
            f"{display_name(user)} created \"{body.title.strip()}\""
            f" and assigned it to {assigned} student(s)",
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


def _past_due(due: str | None) -> bool:
    if not due:
        return False
    try:
        when = datetime.fromisoformat(due)
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) > when


def _reopened(conn: sqlite3.Connection, assignment_id: int) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM access_requests WHERE assignment_id = ? AND status = 'approved'",
            (assignment_id,),
        ).fetchone()
    )


def _locked(conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
    """Is this assignment closed to further editing?

    Past the due date the student loses the editor rather than the exercise:
    they can still read it, and they can ask for it back. An approved request
    hands the editor over again. A submission already reviewed and closed stays
    closed either way.
    """
    if row["status"] in ("approved", "completed"):
        return True
    if not _past_due(row["due_date"]):
        return False
    return not _reopened(conn, int(row["id"]))


def _deny_if_locked(conn: sqlite3.Connection, row: sqlite3.Row) -> None:
    if not _locked(conn, row):
        return
    if row["status"] in ("approved", "completed"):
        raise HTTPException(status_code=409, detail="This exercise is already closed.")
    raise HTTPException(
        status_code=409,
        detail="The deadline for this exercise has passed. Ask your trainer to reopen it.",
    )


def _my_request(conn: sqlite3.Connection, assignment_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, message, created_at, status, decision_message, decided_at"
        " FROM access_requests WHERE assignment_id = ? ORDER BY id DESC LIMIT 1",
        (assignment_id,),
    ).fetchone()
    return dict(row) if row else None


@router.post("/assignments/{assignment_id}/open")
def open_assignment(assignment_id: int, user: sqlite3.Row = Depends(require_student)) -> dict:
    """Mark the exercise opened. The work now happens on the solve page.

    This used to create a notebook seeded with the question. Exercises left the
    notebook in Phase 3; notebooks remain for modules and free practice.
    """
    student_id = int(user["id"])
    now = utcnow()
    with get_conn() as conn:
        row = _load_assignment(conn, assignment_id, student_id)
        status_next = "in_progress" if row["status"] == "assigned" else row["status"]
        conn.execute(
            "UPDATE assignments SET last_opened_at = ?, status = ? WHERE id = ?",
            (now, status_next, assignment_id),
        )
    return {"assignment_id": assignment_id, "status": status_next}


@router.post("/assignments/{assignment_id}/run")
def run_solution(
    assignment_id: int, body: SolutionIn, user: sqlite3.Row = Depends(require_student)
) -> dict:
    """Run the editor's code against the student's own input.

    Deliberately does NOT record a submission: this is the try-it button, and a
    student may press it as often as they like.
    """
    student_id = int(user["id"])
    with get_conn() as conn:
        row = _load_assignment(conn, assignment_id, student_id)
        _deny_if_locked(conn, row)
        conn.execute(
            "UPDATE assignments SET solution_code = ?, last_stdin = ? WHERE id = ?",
            (body.code, body.stdin, assignment_id),
        )

    started = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", body.code],
            input=body.stdin,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_SEC,
            cwd=str(workspace_dir(student_id)),
        )
        stdout, stderr, timed_out = proc.stdout, proc.stderr, False
    except subprocess.TimeoutExpired:
        stdout, stderr, timed_out = "", f"Timed out after {RUN_TIMEOUT_SEC}s.", True

    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    stdout, out_clipped = _clip(stdout)
    stderr, err_clipped = _clip(stderr)
    return {
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "truncated": out_clipped or err_clipped,
        "duration_ms": duration_ms,
    }


@router.post("/assignments/{assignment_id}/check")
def check_solution(
    assignment_id: int, body: SolutionIn, user: sqlite3.Row = Depends(require_student)
) -> dict:
    """Run the editor's code against the exercise's test cases, without submitting.

    This is what Run does now. It tells the student exactly where they stand --
    "2/3 passed", and which one failed and why -- as often as they want, with
    nothing recorded and nothing sent to the trainer. Submit is the deliberate
    act, and stays separate.
    """
    student_id = int(user["id"])
    with get_conn() as conn:
        row = _load_assignment(conn, assignment_id, student_id)
        _deny_if_locked(conn, row)
        conn.execute(
            "UPDATE assignments SET solution_code = ?, last_stdin = ? WHERE id = ?",
            (body.code, body.stdin, assignment_id),
        )
        tests = conn.execute(
            "SELECT stdin, expected_output, is_hidden FROM test_cases"
            " WHERE exercise_id = ? ORDER BY position",
            (row["exercise_id"],),
        ).fetchall()

    return _evaluate(body.code, list(tests), workspace_dir(student_id))


# ── reopening a closed exercise ─────────────────────────────────────────────


@router.post("/assignments/{assignment_id}/access-request", status_code=201)
def raise_access_request(
    assignment_id: int, body: AccessRequestIn, user: sqlite3.Row = Depends(require_student)
) -> dict:
    """Ask the trainer to reopen an exercise whose deadline has passed."""
    student_id = int(user["id"])
    now = utcnow()
    with get_conn() as conn:
        row = _load_assignment(conn, assignment_id, student_id)
        if row["status"] in ("approved", "completed"):
            raise HTTPException(status_code=409, detail="This exercise is already closed.")
        if not _past_due(row["due_date"]):
            raise HTTPException(
                status_code=409,
                detail="This exercise is still open — you can edit and submit it now.",
            )
        if _reopened(conn, assignment_id):
            raise HTTPException(
                status_code=409, detail="Your trainer has already reopened this exercise."
            )
        if conn.execute(
            "SELECT 1 FROM access_requests WHERE assignment_id = ? AND status = 'pending'",
            (assignment_id,),
        ).fetchone():
            raise HTTPException(
                status_code=409, detail="You already have a request waiting on this exercise."
            )

        trainer_id = int(row["trainer_id"])
        cur = conn.execute(
            "INSERT INTO access_requests (assignment_id, exercise_id, student_id, trainer_id,"
            " message, created_at, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
            (assignment_id, int(row["exercise_id"]), student_id, trainer_id,
             body.message.strip(), now),
        )
        title = row["title"]
        who = display_name(user)
        notify(conn, trainer_id, "query", f'{who} asked to reopen "{title}"', "/trainer")
        record_activity(
            conn, trainer_id, "query", f'{who} asked to reopen "{title}"',
            student_id, "/trainer",
        )
        record_activity(
            conn, student_id, "query", f'You asked to reopen "{title}"',
            student_id, "/student",
        )
    return {"id": int(cur.lastrowid), "status": "pending"}


@router.get("/access-requests")
def list_access_requests(
    status_filter: str | None = Query(None, alias="status"),
    user: sqlite3.Row = Depends(require_trainer),
) -> list[dict]:
    """Every reopen request on this trainer's exercises, newest first."""
    where, params = "r.trainer_id = ?", [int(user["id"])]
    if status_filter in ("pending", "approved", "rejected"):
        where += " AND r.status = ?"
        params.append(status_filter)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT r.*, e.title, u.full_name AS student_name, u.email AS student_email,"
            "       a.due_date"
            " FROM access_requests r"
            " JOIN exercises e ON e.id = r.exercise_id"
            " JOIN users u ON u.id = r.student_id"
            " JOIN assignments a ON a.id = r.assignment_id"
            f" WHERE {where} ORDER BY r.created_at DESC, r.id DESC",
            params,
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["student_display"] = _display(item, "student_name", "student_email")
        out.append(item)
    return out


@router.post("/access-requests/{request_id}/decide")
def decide_access_request(
    request_id: int, body: AccessDecisionIn, user: sqlite3.Row = Depends(require_trainer)
) -> dict:
    """Approve or reject one student's request, with a message for them alone."""
    trainer_id = int(user["id"])
    now = utcnow()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT r.*, e.title FROM access_requests r"
            " JOIN exercises e ON e.id = r.exercise_id"
            " WHERE r.id = ? AND r.trainer_id = ?",
            (request_id, trainer_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Request not found.")
        if row["status"] != "pending":
            raise HTTPException(status_code=409, detail="This request has already been answered.")

        status_next = "approved" if body.action == "approve" else "rejected"
        conn.execute(
            "UPDATE access_requests SET status = ?, decision_message = ?, decided_at = ?,"
            " decided_by = ? WHERE id = ?",
            (status_next, body.message.strip(), now, trainer_id, request_id),
        )
        # Approval hands the editor back; the assignment leaves whatever
        # terminal-looking state the deadline left it in.
        if status_next == "approved":
            conn.execute(
                "UPDATE assignments SET status = CASE WHEN status = 'assigned'"
                " THEN 'assigned' ELSE status END WHERE id = ?",
                (int(row["assignment_id"]),),
            )

        title = row["title"]
        student_id = int(row["student_id"])
        headline = (
            f'Reopened: {title}' if status_next == "approved"
            else f'Reopen request declined: {title}'
        )
        notify(conn, student_id, status_next, headline, "/student/exercises")
        record_activity(
            conn, student_id, status_next,
            f'{display_name(user)} {"reopened" if status_next == "approved" else "declined to reopen"}'
            f' "{title}"',
            trainer_id, "/student/exercises",
        )
    return {"id": request_id, "status": status_next, "message": body.message.strip()}


@router.patch("/assignments/{assignment_id}/code")
def save_solution(
    assignment_id: int, body: SolutionIn, user: sqlite3.Row = Depends(require_student)
) -> dict:
    """Autosave the editor, so a refresh never loses work."""
    student_id = int(user["id"])
    now = utcnow()
    with get_conn() as conn:
        row = _load_assignment(conn, assignment_id, student_id)
        _deny_if_locked(conn, row)
        status_next = "in_progress" if row["status"] == "assigned" else row["status"]
        conn.execute(
            "UPDATE assignments SET solution_code = ?, last_stdin = ?,"
            " last_opened_at = ?, status = ? WHERE id = ?",
            (body.code, body.stdin, now, status_next, assignment_id),
        )
    return {"ok": True}


@router.post("/assignments/{assignment_id}/submit")
def submit_assignment(assignment_id: int, user: sqlite3.Row = Depends(require_student)) -> dict:
    """Submit the notebook's code and evaluate it automatically (SRS §11, §12)."""
    student_id = int(user["id"])
    now = utcnow()
    with get_conn() as conn:
        row = _load_assignment(conn, assignment_id, student_id)
        _deny_if_locked(conn, row)

        code = row["solution_code"] or ""
        if not code.strip():
            raise HTTPException(
                status_code=409, detail="Write some code before submitting."
            )
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
            f"{display_name(user)} submitted \"{title}\"",
            "/trainer",
        )
        record_activity(
            conn,
            int(row["trainer_id"]),
            "submitted",
            f"{display_name(user)} submitted \"{title}\""
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
        # What the solve page needs to decide whether to hand over the editor,
        # and what to tell the student if it does not.
        locked = _locked(conn, row)
        past_due = _past_due(row["due_date"])
        access_request = _my_request(conn, assignment_id)

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
            "starter_code",
        )
    }
    return {
        "id": row["id"],
        "status": row["status"],
        "due_date": row["due_date"],
        "notebook_id": row["notebook_id"],
        "solution_code": row["solution_code"],
        "last_stdin": row["last_stdin"],
        "exercise": exercise,
        "public_tests": public_tests,
        "hidden_tests": hidden,
        "history": history,
        "locked": locked,
        "past_due": past_due,
        "access_request": access_request,
    }


# ══════════════════════ Phase B: detail views and queries ══════════════════


@router.get("/students/{student_id}")
def student_detail(student_id: int, user: sqlite3.Row = Depends(require_trainer)) -> dict:
    """One student: who they are, and every exercise this trainer gave them.

    Backs the student detail page, its personal-information page and the
    per-exercise timeline (req 2).
    """
    trainer_id = int(user["id"])
    with get_conn() as conn:
        student = conn.execute(
            "SELECT id, email, full_name, first_name, last_name, phone, role,"
            "       is_active, created_at"
            " FROM users WHERE id = ? AND role = 'student'",
            (student_id,),
        ).fetchone()
        if not student:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such student")

        exercises = conn.execute(
            "SELECT a.id AS assignment_id, a.status, a.assigned_at, a.due_date,"
            "       a.last_opened_at, a.notebook_id,"
            "       e.id AS exercise_id, e.title, e.problem_statement,"
            "       s.id AS submission_id, s.submitted_at, s.tests_passed, s.tests_total,"
            "       s.result, s.review_status, s.comment, s.reviewed_at"
            " FROM assignments a"
            " JOIN exercises e ON e.id = a.exercise_id"
            " LEFT JOIN submissions s ON s.assignment_id = a.id"
            " WHERE a.student_id = ? AND e.trainer_id = ?"
            " ORDER BY a.assigned_at DESC",
            (student_id, trainer_id),
        ).fetchall()

        queries = conn.execute(
            "SELECT q.*, e.title AS exercise"
            " FROM queries q"
            " JOIN assignments a ON a.id = q.assignment_id"
            " JOIN exercises e ON e.id = a.exercise_id"
            " WHERE q.student_id = ? AND q.trainer_id = ?"
            " ORDER BY q.created_at DESC",
            (student_id, trainer_id),
        ).fetchall()

        # Requirement 17: module completion sits beside exercise completion.
        module_rows = []
        for m in conn.execute(
            "SELECT m.id, m.title, m.description, a.assigned_at FROM module_assignments a"
            " JOIN modules m ON m.id = a.module_id"
            " WHERE a.student_id = ? AND m.trainer_id = ?"
            " ORDER BY a.assigned_at DESC",
            (student_id, trainer_id),
        ):
            total = conn.execute(
                "SELECT COUNT(*) FROM module_blocks WHERE module_id = ? AND kind = 'code'",
                (m["id"],),
            ).fetchone()[0]
            done = conn.execute(
                "SELECT COUNT(*) FROM module_progress"
                " WHERE module_id = ? AND student_id = ? AND ran_ok = 1",
                (m["id"], student_id),
            ).fetchone()[0]
            module_rows.append(
                {
                    **dict(m),
                    "code_blocks": total,
                    "completed_blocks": done,
                    "progress": round(100 * done / total) if total else 0,
                }
            )

    rows = [dict(r) for r in exercises]
    completed = sum(1 for r in rows if r["status"] == "completed")
    submitted = [r for r in rows if r["submitted_at"]]
    # Late means it arrived after its due date. No due date is never late.
    for r in rows:
        r["late"] = bool(r["due_date"] and r["submitted_at"] and r["submitted_at"] > r["due_date"])
    late = sum(1 for r in rows if r["late"])
    graded = [r for r in submitted if r["tests_total"]]
    return {
        "student": {**dict(student), "display": display_name(student)},
        "exercises": rows,
        "modules": module_rows,
        "queries": [dict(q) for q in queries],
        "assigned": len(rows),
        "completed": completed,
        "pending": sum(1 for r in rows if r["status"] in OPEN_STATUSES),
        "awaiting": sum(1 for r in rows if r["status"] == "submitted"),
        "late": late,
        "on_time_rate": round(100 * (len(submitted) - late) / len(submitted)) if submitted else 100,
        "avg_tests": round(
            100 * sum(r["tests_passed"] for r in graded) / sum(r["tests_total"] for r in graded)
        ) if graded else 0,
        "last_active": max((r["last_opened_at"] for r in rows if r["last_opened_at"]), default=None),
        "progress": round(100 * completed / len(rows)) if rows else 0,
    }


@router.get("/exercises/{exercise_id}")
def exercise_detail(exercise_id: int, user: sqlite3.Row = Depends(require_trainer)) -> dict:
    """Everything about one exercise, for its detail page (req 8)."""
    trainer_id = int(user["id"])
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM exercises WHERE id = ? AND trainer_id = ?",
            (exercise_id, trainer_id),
        ).fetchone()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such exercise")

        item = dict(row)
        item["test_cases"] = [
            dict(t)
            for t in conn.execute(
                "SELECT id, position, stdin, expected_output, is_hidden FROM test_cases"
                " WHERE exercise_id = ? ORDER BY position",
                (exercise_id,),
            )
        ]
        item["students"] = [
            dict(s)
            for s in conn.execute(
                "SELECT u.id, u.full_name, u.email, a.id AS assignment_id, a.status,"
                "       a.assigned_at, a.due_date"
                " FROM assignments a JOIN users u ON u.id = a.student_id"
                " WHERE a.exercise_id = ? ORDER BY u.full_name COLLATE NOCASE",
                (exercise_id,),
            )
        ]
        for s in item["students"]:
            s["display"] = _display(s, "full_name")
        item["submissions"] = [
            dict(s)
            for s in conn.execute(
                "SELECT s.id, s.student_id, s.submitted_at, s.result, s.tests_passed,"
                "       s.tests_total, s.review_status, u.full_name AS student, u.email"
                " FROM submissions s JOIN users u ON u.id = s.student_id"
                " WHERE s.exercise_id = ? ORDER BY s.submitted_at DESC",
                (exercise_id,),
            )
        ]
        for s in item["submissions"]:
            s["display"] = _display(s, "student")
    return item


@router.post("/exercises/{exercise_id}/assign")
def assign_exercise(
    exercise_id: int, body: AssignIn, user: sqlite3.Row = Depends(require_trainer)
) -> dict:
    """Assign an existing exercise, publishing it if it was still a draft (req 6)."""
    trainer_id = int(user["id"])
    now = utcnow()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM exercises WHERE id = ? AND trainer_id = ?",
            (exercise_id, trainer_id),
        ).fetchone()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such exercise")

        # Assigning a draft is how a trainer publishes it from the drafts page.
        if row["status"] != "published":
            conn.execute(
                "UPDATE exercises SET status = 'published', updated_at = ? WHERE id = ?",
                (now, exercise_id),
            )

        valid = {
            int(r["id"])
            for r in conn.execute(
                "SELECT id FROM users WHERE role = 'student' AND is_active = 1"
            )
        }
        title = row["title"]
        actor = display_name(user)
        assigned = 0
        for student_id in dict.fromkeys(body.assign_to):
            if int(student_id) not in valid:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO assignments (exercise_id, student_id, assigned_by,"
                " assigned_at, due_date, status) VALUES (?, ?, ?, ?, ?, 'assigned')",
                (exercise_id, student_id, trainer_id, now, row["due_date"]),
            )
            assigned += 1
            notify(conn, student_id, "assigned", f"New exercise assigned: {title}", "/student")
            record_activity(
                conn,
                student_id,
                "assigned",
                f'{actor} assigned "{title}"',
                trainer_id,
                "/student",
            )
    return {"id": exercise_id, "assigned": assigned}


@router.post("/assignments/{assignment_id}/query", status_code=status.HTTP_201_CREATED)
def raise_query(
    assignment_id: int, body: QueryIn, user: sqlite3.Row = Depends(require_trainer)
) -> dict:
    """Raise a query or warning on an assignment the student has not sent in (req 12)."""
    trainer_id = int(user["id"])
    now = utcnow()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT a.id, a.student_id, e.title FROM assignments a"
            " JOIN exercises e ON e.id = a.exercise_id"
            " WHERE a.id = ? AND e.trainer_id = ?",
            (assignment_id, trainer_id),
        ).fetchone()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such assignment")

        title = row["title"]
        actor = display_name(user)
        cur = conn.execute(
            "INSERT INTO queries (assignment_id, trainer_id, student_id, severity,"
            " message, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (assignment_id, trainer_id, row["student_id"], body.severity, body.message, now),
        )
        notify(
            conn,
            row["student_id"],
            "query",
            f'{body.severity.title()} on "{title}"',
            "/student",
        )
        record_activity(
            conn,
            row["student_id"],
            "query",
            f'{actor} raised a {body.severity} on "{title}"',
            trainer_id,
            "/student",
        )
    return {"id": int(cur.lastrowid), "severity": body.severity}


@router.post("/queries/{query_id}/reply")
def reply_to_query(
    query_id: int, body: QueryReplyIn, user: sqlite3.Row = Depends(require_student)
) -> dict:
    """The student's one reply to a trainer's query (req 12)."""
    student_id = int(user["id"])
    now = utcnow()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM queries WHERE id = ? AND student_id = ?", (query_id, student_id)
        ).fetchone()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such query")
        if row["reply"]:
            raise HTTPException(status.HTTP_409_CONFLICT, "This query already has a reply")

        conn.execute(
            "UPDATE queries SET reply = ?, replied_at = ? WHERE id = ?",
            (body.reply, now, query_id),
        )
        notify(
            conn,
            row["trainer_id"],
            "reviewed",
            f"{display_name(user)} replied to your query",
            "/trainer",
        )
    return {"id": query_id, "reply": body.reply}

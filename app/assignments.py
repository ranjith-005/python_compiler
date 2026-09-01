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

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .config import settings
from .db import create_notebook, get_conn, notify, record_activity, utcnow
from .deps import get_current_user, require_student, require_trainer
from .schemas import AssignIn, ExerciseIn, QueryIn, QueryReplyIn, ReviewIn
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
    intro = [f"# {row['title']}", "", "## Question", "", row["problem_statement"] or "Work through the steps below."]
    if row["due_date"]:
        intro += ["", f"> Due: {row['due_date']}"]
    context = ["## Understand the input and output"]
    if row["input_format"]:
        context += ["", "**Input**", "", row["input_format"]]
    if row["output_format"]:
        context += ["", "**Output**", "", row["output_format"]]
    if row["constraints"]:
        context += ["", "**Constraints**", "", row["constraints"]]
    if row["sample_input"] or row["sample_output"]:
        context += ["", "**Example**", "", "Input:", "```", row["sample_input"] or "", "```", "Output:", "```", row["sample_output"] or "", "```"]
    explanation = ["## Plan your solution", "", row["explanation"] or "Break the problem into small steps, then test each step.", "", "> `input()` returns text. Use `int(input())` before arithmetic with numbers."]
    public = [t for t in tests if not t["is_hidden"]]
    if public:
        explanation += ["", f"There are {len(public)} public test case(s) available when you submit."]
    starter = row["starter_code"] or "# Write your solution here.\n"
    return [
        ("markdown", "\n".join(intro)),
        ("code", starter),
        ("markdown", "\n".join(context)),
        ("code", "# Step 2: add a small test or helper while you work.\n"),
        ("markdown", "\n".join(explanation)),
        ("code", "# Step 3: improve your solution, then run and submit it.\n"),
    ]


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
    return {
        "student": dict(student),
        "exercises": rows,
        "modules": module_rows,
        "queries": [dict(q) for q in queries],
        "assigned": len(rows),
        "completed": completed,
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
        actor = user["full_name"] or user["email"]
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
        actor = user["full_name"] or user["email"]
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
            f"{user['full_name'] or user['email']} replied to your query",
            "/trainer",
        )
    return {"id": query_id, "reply": body.reply}

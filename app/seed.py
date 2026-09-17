"""Demo data for the dashboards: `python -m app.seed` (add --reset to redo it).

Creates one trainer, four students, four coding exercises and a spread of
assignments and submissions, so both dashboards show real numbers on a fresh
database instead of empty panels.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from .db import get_conn, init_db, notify, record_activity, utcnow
from .security import hash_password

TRAINERS = [
    ("trainer@test.com", "Demo Trainer"),
    ("trainer@pycompiler.dev", "Priya Raman"),
]
TRAINER = TRAINERS[0]
TRAINER_PASSWORD = "trainer1234"
STUDENT_PASSWORD = "student1234"
STUDENTS = [
    ("student@test.com", "Demo Student"),
    ("student@pycompiler.dev", "Test Student"),
    ("aditi@pycompiler.dev", "Aditi Sharma"),
    ("rahul@pycompiler.dev", "Rahul Verma"),
    ("meera@pycompiler.dev", "Meera Nair"),
    ("karthik@pycompiler.dev", "Karthik Iyer"),
]
DEMO_EMAILS = [email for email, _ in TRAINERS] + [email for email, _ in STUDENTS]


def when(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat(timespec="seconds")


EXERCISES = [
    {
        "title": "Sum of two numbers",
        "problem_statement": "Read two integers from standard input, one per line, "
        "and print their sum.",
        "input_format": "Two integers, each on its own line.",
        "output_format": "A single integer: the sum.",
        "sample_input": "3\n4",
        "sample_output": "7",
        "explanation": "3 + 4 = 7.",
        "constraints": "-10^9 <= a, b <= 10^9",
        "starter_code": "a = int(input())\nb = int(input())\n# print the sum\n",
        "due": when(days=3),
        "status": "published",
        "tests": [
            ("3\n4", "7", 0),
            ("-5\n5", "0", 0),
            ("1000000000\n1000000000", "2000000000", 1),
        ],
    },
    {
        "title": "FizzBuzz",
        "problem_statement": "Read an integer n and print the numbers 1 to n, one per "
        "line, replacing multiples of 3 with Fizz, multiples of 5 with Buzz, and "
        "multiples of both with FizzBuzz.",
        "input_format": "A single integer n.",
        "output_format": "n lines.",
        "sample_input": "5",
        "sample_output": "1\n2\nFizz\n4\nBuzz",
        "explanation": "3 is a multiple of 3, 5 is a multiple of 5.",
        "constraints": "1 <= n <= 1000",
        "starter_code": "n = int(input())\n# print each line\n",
        "due": when(days=6),
        "status": "published",
        "tests": [
            ("5", "1\n2\nFizz\n4\nBuzz", 0),
            ("15", "1\n2\nFizz\n4\nBuzz\nFizz\n7\n8\nFizz\nBuzz\n11\nFizz\n13\n14\nFizzBuzz", 1),
        ],
    },
    {
        "title": "Reverse a string",
        "problem_statement": "Read a line of text and print it reversed.",
        "input_format": "One line of text.",
        "output_format": "The reversed line.",
        "sample_input": "python",
        "sample_output": "nohtyp",
        "explanation": "Each character in reverse order.",
        "constraints": "The line is at most 1000 characters.",
        "starter_code": "s = input()\n# print s reversed\n",
        "due": when(days=-1),
        "status": "published",
        "tests": [("python", "nohtyp", 0), ("level", "level", 0)],
    },
    {
        "title": "Count vowels",
        "problem_statement": "Read a line and print how many vowels it contains.",
        "input_format": "One line of text.",
        "output_format": "A single integer.",
        "sample_input": "beautiful",
        "sample_output": "5",
        "explanation": "e, a, u, i, u.",
        "constraints": "",
        "starter_code": "s = input()\n",
        "due": when(days=10),
        "status": "draft",
        "tests": [("beautiful", "5", 0)],
    },
]

GOOD_SUM = "a = int(input())\nb = int(input())\nprint(a + b)\n"
BAD_SUM = "a = int(input())\nb = int(input())\nprint(a - b)\n"
GOOD_REVERSE = "s = input()\nprint(s[::-1])\n"


def _create_user(conn: sqlite3.Connection, email: str, name: str, role: str, password: str) -> int:
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, created_at, role, full_name, is_active)"
        " VALUES (?, ?, ?, ?, ?, 1)",
        (email, hash_password(password), utcnow(), role, name),
    )
    return int(cur.lastrowid)


def _assign(conn: sqlite3.Connection, exercise_id: int, student_id: int, trainer_id: int,
            due: str | None, status: str, opened: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO assignments (exercise_id, student_id, assigned_by, assigned_at,"
        " due_date, status, last_opened_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (exercise_id, student_id, trainer_id, when(days=-4), due, status, opened),
    )
    return int(cur.lastrowid)


def _submit(conn: sqlite3.Connection, assignment_id: int, student_id: int, exercise_id: int,
            code: str, result: str, passed: int, total: int, submitted_at: str,
            review_status: str = "pending", comment: str = "",
            reviewed_at: str | None = None, reviewed_by: int | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO submissions (assignment_id, student_id, exercise_id, code, submitted_at,"
        " result, tests_total, tests_passed, review_status, comment, reviewed_at, reviewed_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (assignment_id, student_id, exercise_id, code, submitted_at, result, total, passed,
         review_status, comment, reviewed_at, reviewed_by),
    )
    return int(cur.lastrowid)


def _query(conn: sqlite3.Connection, assignment_id: int, exercise_id: int, student_id: int,
           trainer_id: int, message: str, created_at: str, status: str = "pending",
           decision_message: str = "", decided_at: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO access_requests (assignment_id, exercise_id, student_id, trainer_id,"
        " message, created_at, status, decision_message, decided_at, decided_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (assignment_id, exercise_id, student_id, trainer_id, message, created_at,
         status, decision_message, decided_at, trainer_id if decided_at else None),
    )
    return int(cur.lastrowid)


def reset(conn: sqlite3.Connection) -> None:
    """Remove the demo accounts; cascades take their exercises and work with them."""
    placeholders = ",".join("?" * len(DEMO_EMAILS))
    conn.execute(f"DELETE FROM users WHERE email IN ({placeholders})", DEMO_EMAILS)


def seed() -> None:
    init_db()
    wants_reset = "--reset" in sys.argv

    with get_conn() as conn:
        if wants_reset:
            reset(conn)
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?", (TRAINERS[0][0],)
        ).fetchone()
        if existing:
            print(
                f"Demo data already present ({TRAINERS[0][0]}).\n"
                "Run `python -m app.seed --reset` to recreate it."
            )
            return

        trainer_id = _create_user(conn, TRAINERS[0][0], TRAINERS[0][1], "trainer", TRAINER_PASSWORD)
        for email, name in TRAINERS[1:]:
            _create_user(conn, email, name, "trainer", TRAINER_PASSWORD)

        student_ids = [
            _create_user(conn, email, name, "student", STUDENT_PASSWORD)
            for email, name in STUDENTS
        ]
        demo_student, test_student, aditi, rahul, meera, karthik = student_ids

        exercise_ids = {}
        for spec in EXERCISES:
            cur = conn.execute(
                "INSERT INTO exercises (trainer_id, title, problem_statement, input_format,"
                " output_format, sample_input, sample_output, explanation, constraints,"
                " starter_code, due_date, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    trainer_id, spec["title"], spec["problem_statement"], spec["input_format"],
                    spec["output_format"], spec["sample_input"], spec["sample_output"],
                    spec["explanation"], spec["constraints"], spec["starter_code"],
                    spec["due"], spec["status"], when(days=-5), when(days=-5),
                ),
            )
            exercise_id = int(cur.lastrowid)
            exercise_ids[spec["title"]] = exercise_id
            for position, (stdin, expected, hidden) in enumerate(spec["tests"]):
                conn.execute(
                    "INSERT INTO test_cases (exercise_id, position, stdin, expected_output,"
                    " is_hidden) VALUES (?, ?, ?, ?, ?)",
                    (exercise_id, position, stdin, expected, hidden),
                )
            record_activity(
                conn, trainer_id, "created", f'Created "{spec["title"]}"', trainer_id, "/trainer"
            )

        summing = exercise_ids["Sum of two numbers"]
        fizz = exercise_ids["FizzBuzz"]
        reverse = exercise_ids["Reverse a string"]

        # ── Sum of two numbers: assigned to everyone, mixed progress ──────────
        a_sum = {
            student: _assign(conn, summing, student, trainer_id, when(days=3), status, opened)
            for student, status, opened in (
                (demo_student, "in_progress", when(hours=-2)),
                (aditi, "completed", when(days=-2)),
                (rahul, "submitted", when(days=-1)),
                (meera, "in_progress", when(hours=-5)),
                (karthik, "assigned", None),
            )
        }
        _submit(
            conn, a_sum[aditi], aditi, summing, GOOD_SUM, "accepted", 3, 3, when(days=-2),
            "approved", "Clean and correct — nicely done.", when(days=-2), trainer_id,
        )
        _submit(
            conn, a_sum[rahul], rahul, summing, BAD_SUM, "wrong_answer", 0, 3, when(days=-1),
        )

        # ── FizzBuzz: students with assigned / submitted / rework needed ──────
        a_fizz = {
            student: _assign(conn, fizz, student, trainer_id, when(days=6), status, opened)
            for student, status, opened in (
                (demo_student, "assigned", None),
                (aditi, "submitted", when(hours=-8)),
                (rahul, "assigned", None),
                (meera, "in_progress", when(days=-1)),
            )
        }
        _submit(
            conn, a_fizz[aditi], aditi, fizz,
            'n = int(input())\nfor i in range(1, n + 1):\n'
            '    if i % 15 == 0:\n        print("FizzBuzz")\n'
            '    elif i % 3 == 0:\n        print("Fizz")\n'
            '    elif i % 5 == 0:\n        print("Buzz")\n'
            '    else:\n        print(i)\n',
            "accepted", 2, 2, when(hours=-8),
        )
        _submit(
            conn, a_fizz[meera], meera, fizz,
            'n = int(input())\nfor i in range(1, n):\n    print(i)\n',
            "wrong_answer", 0, 2, when(days=-1), "changes_requested",
            "The loop stops one short and the Fizz/Buzz cases are missing. "
            "Check the range bounds and handle multiples of 3 and 5.",
            when(days=-1), trainer_id,
        )

        # ── Reverse a string: overdue for students, so pending ───────────────
        a_rev = {
            student: _assign(conn, reverse, student, trainer_id, when(days=-1), status, opened)
            for student, status, opened in (
                (demo_student, "pending", None),
                (meera, "pending", None),
                (karthik, "pending", when(days=-2)),
                (rahul, "completed", when(days=-3)),
            )
        }
        _submit(
            conn, a_rev[rahul], rahul, reverse, GOOD_REVERSE, "accepted", 2, 2, when(days=-3),
            "approved", "Slicing is exactly the right tool here.", when(days=-3), trainer_id,
        )

        # ── queries on the overdue exercise: one waiting, two already answered ─
        # These feed the trainer's Query raised card and its queries page: the
        # pending one waits for a decision, the decided ones sit in the history.
        _query(
            conn, a_rev[meera], reverse, meera, trainer_id,
            "I was travelling last week and missed the deadline. Can I still submit it?",
            when(hours=-3),
        )
        _query(
            conn, a_rev[karthik], reverse, karthik, trainer_id,
            "Please give me one more day to finish it.", when(days=-2),
            "approved", "One more day — make it count.", when(days=-1),
        )
        _query(
            conn, a_rev[demo_student], reverse, demo_student, trainer_id,
            "I forgot the deadline, sorry.", when(days=-2),
            "rejected", "The deadline was already a week long.", when(days=-1),
        )
        notify(
            conn, trainer_id, "query", 'Meera Nair asked to reopen "Reverse a string"',
            "/trainer",
        )
        record_activity(
            conn, trainer_id, "query", 'Meera Nair asked to reopen "Reverse a string"',
            meera, "/trainer",
        )
        notify(conn, karthik, "approved", "Reopened: Reverse a string", "/student/exercises")
        record_activity(
            conn, karthik, "approved", 'Demo Trainer reopened "Reverse a string"',
            trainer_id, "/student/exercises",
        )
        notify(
            conn, demo_student, "rejected", "Reopen request declined: Reverse a string",
            "/student/exercises",
        )
        record_activity(
            conn, demo_student, "rejected", 'Demo Trainer declined to reopen "Reverse a string"',
            trainer_id, "/student/exercises",
        )

        # ── notifications and activity feeds (§17) ───────────────────────────
        notify(conn, trainer_id, "submitted", 'Rahul Verma submitted "Sum of two numbers"', "/trainer")
        notify(conn, trainer_id, "submitted", 'Aditi Sharma submitted "FizzBuzz"', "/trainer")
        record_activity(
            conn, trainer_id, "submitted",
            'Rahul Verma submitted "Sum of two numbers" - 0/3 tests passed', rahul, "/trainer",
        )
        record_activity(
            conn, trainer_id, "submitted",
            'Aditi Sharma submitted "FizzBuzz" - 2/2 tests passed', aditi, "/trainer",
        )
        record_activity(
            conn, trainer_id, "reviewed", 'Requested modifications on "FizzBuzz" from Meera Nair',
            trainer_id, "/trainer",
        )

        for student in student_ids:
            notify(conn, student, "assigned", 'New exercise assigned: Sum of two numbers', "/student")
            record_activity(
                conn, student, "assigned", 'Demo Trainer assigned "Sum of two numbers"',
                trainer_id, "/student",
            )
        notify(conn, meera, "request_changes", "Changes requested: FizzBuzz", "/student")
        record_activity(conn, meera, "request_changes", "Changes requested: FizzBuzz", trainer_id, "/student")
        notify(conn, aditi, "approve", "Solution approved: Sum of two numbers", "/student")
        record_activity(conn, aditi, "approve", "Solution approved: Sum of two numbers", trainer_id, "/student")
        record_activity(conn, rahul, "submitted", 'Submitted "Sum of two numbers" - wrong answer', rahul, "/student")

    print("Demo data created.\n")
    for email, name in TRAINERS:
        print(f"  Trainer   {email}  /  {TRAINER_PASSWORD}   ({name})")
    for email, name in STUDENTS:
        print(f"  Student   {email}  /  {STUDENT_PASSWORD}   ({name})")
    print("\nSign in at http://127.0.0.1:8000/login")


def ensure_default_accounts() -> None:
    """Ensure baseline test accounts exist so the platform can be tested immediately."""
    init_db()
    with get_conn() as conn:
        trainer = conn.execute("SELECT id FROM users WHERE role = 'trainer'").fetchone()
        if not trainer:
            seed()
            return

        # Ensure demo trainer and student exist
        for email, name, role, pwd in [
            (TRAINERS[0][0], TRAINERS[0][1], "trainer", TRAINER_PASSWORD),
            (STUDENTS[0][0], STUDENTS[0][1], "student", STUDENT_PASSWORD),
        ]:
            row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if not row:
                _create_user(conn, email, name, role, pwd)


if __name__ == "__main__":
    seed()

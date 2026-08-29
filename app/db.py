"""SQLite access: connection factory and idempotent schema creation."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email COLLATE NOCASE);

-- Legacy table from the retired script editor. Kept only so that an older
-- database still has its saved scripts migrated into notebooks below.
CREATE TABLE IF NOT EXISTS snippets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    code       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, name)
);

CREATE TABLE IF NOT EXISTS notebooks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notebooks_user ON notebooks(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS cells (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    notebook_id     INTEGER NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,
    cell_type       TEXT NOT NULL DEFAULT 'code',
    source          TEXT NOT NULL DEFAULT '',
    outputs         TEXT NOT NULL DEFAULT '[]',
    execution_count INTEGER,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cells_notebook ON cells(notebook_id, position);

CREATE TABLE IF NOT EXISTS migrations (
    key        TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""

# ── Assignment & review platform (SRS §2-§21) ────────────────────────────────
# Added alongside the notebook tables above; a notebook is what a student
# actually works in, so `assignments.notebook_id` links the two.

PLATFORM_SCHEMA = """
CREATE TABLE IF NOT EXISTS exercises (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    trainer_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title             TEXT NOT NULL,
    problem_statement TEXT NOT NULL DEFAULT '',
    input_format      TEXT NOT NULL DEFAULT '',
    output_format     TEXT NOT NULL DEFAULT '',
    sample_input      TEXT NOT NULL DEFAULT '',
    sample_output     TEXT NOT NULL DEFAULT '',
    explanation       TEXT NOT NULL DEFAULT '',
    constraints       TEXT NOT NULL DEFAULT '',
    starter_code      TEXT NOT NULL DEFAULT '',
    due_date          TEXT,
    status            TEXT NOT NULL DEFAULT 'draft',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exercises_trainer ON exercises(trainer_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS test_cases (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id     INTEGER NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL DEFAULT 0,
    stdin           TEXT NOT NULL DEFAULT '',
    expected_output TEXT NOT NULL DEFAULT '',
    is_hidden       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_test_cases_exercise ON test_cases(exercise_id, position);

CREATE TABLE IF NOT EXISTS assignments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id    INTEGER NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    student_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assigned_by    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assigned_at    TEXT NOT NULL,
    due_date       TEXT,
    status         TEXT NOT NULL DEFAULT 'assigned',
    notebook_id    INTEGER REFERENCES notebooks(id) ON DELETE SET NULL,
    last_opened_at TEXT,
    UNIQUE(exercise_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_assignments_student ON assignments(student_id, status);

CREATE TABLE IF NOT EXISTS submissions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    student_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exercise_id   INTEGER NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    code          TEXT NOT NULL DEFAULT '',
    submitted_at  TEXT NOT NULL,
    result        TEXT NOT NULL DEFAULT 'pending',
    tests_total   INTEGER NOT NULL DEFAULT 0,
    tests_passed  INTEGER NOT NULL DEFAULT 0,
    review_status TEXT NOT NULL DEFAULT 'pending',
    comment       TEXT NOT NULL DEFAULT '',
    reviewed_at   TEXT,
    reviewed_by   INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_submissions_review ON submissions(review_status, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_submissions_assignment ON submissions(assignment_id, submitted_at DESC);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    title      TEXT NOT NULL,
    link       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    read_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS activities (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    actor_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    kind       TEXT NOT NULL,
    summary    TEXT NOT NULL,
    link       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activities_user ON activities(user_id, created_at DESC);
"""


WELCOME_CELLS = [
    (
        "code",
        "# Welcome to your notebook. Shift+Enter runs a cell.\n"
        "# Variables stay alive between cells, just like Colab.\n"
        "import numpy as np\n\n"
        "data = np.arange(10) ** 2\n"
        "data",
    ),
    ("code", "# `data` is still here from the cell above.\nprint(data.sum())"),
    (
        "code",
        "import matplotlib.pyplot as plt\n\n"
        "plt.plot(data, marker='o')\n"
        "plt.title('Squares')\n"
        "plt.show()",
    ),
]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """Transactional connection: commits on success, rolls back on error."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.executescript(PLATFORM_SCHEMA)
        _migrate_user_columns(conn)
        _migrate_snippets_to_notebooks(conn)


def _migrate_snippets_to_notebooks(conn: sqlite3.Connection) -> None:
    """Carry pre-notebook saved scripts over as single-cell notebooks."""
    key = "snippets_to_notebooks_v1"
    if conn.execute("SELECT 1 FROM migrations WHERE key = ?", (key,)).fetchone():
        return
    now = utcnow()
    for row in conn.execute(
        "SELECT user_id, name, code, created_at FROM snippets ORDER BY id"
    ).fetchall():
        cur = conn.execute(
            "INSERT INTO notebooks (user_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (row["user_id"], row["name"], row["created_at"], now),
        )
        conn.execute(
            "INSERT INTO cells (notebook_id, position, cell_type, source, outputs, updated_at)"
            " VALUES (?, 0, 'code', ?, '[]', ?)",
            (cur.lastrowid, row["code"], now),
        )
    conn.execute("INSERT INTO migrations (key, applied_at) VALUES (?, ?)", (key, now))


def create_notebook(conn: sqlite3.Connection, user_id: int, name: str, cells=None) -> int:
    """Create a notebook with `cells` (list of (cell_type, source)) or a blank code cell."""
    now = utcnow()
    cur = conn.execute(
        "INSERT INTO notebooks (user_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (user_id, name, now, now),
    )
    notebook_id = int(cur.lastrowid)
    for position, (cell_type, source) in enumerate(cells or [("code", "")]):
        conn.execute(
            "INSERT INTO cells (notebook_id, position, cell_type, source, outputs, updated_at)"
            " VALUES (?, ?, ?, ?, '[]', ?)",
            (notebook_id, position, cell_type, source, now),
        )
    return notebook_id


def _migrate_user_columns(conn: sqlite3.Connection) -> None:
    """Add the platform columns to an accounts table created before roles existed."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    for column, ddl in (
        ("role", "TEXT NOT NULL DEFAULT 'student'"),
        ("full_name", "TEXT NOT NULL DEFAULT ''"),
        ("first_name", "TEXT NOT NULL DEFAULT ''"),
        ("last_name", "TEXT NOT NULL DEFAULT ''"),
        ("phone", "TEXT NOT NULL DEFAULT ''"),
        ("is_active", "INTEGER NOT NULL DEFAULT 1"),
    ):
        if column not in existing:
            conn.execute(f"ALTER TABLE users ADD COLUMN {column} {ddl}")

    # Preserve readable names for accounts created before name parts were stored.
    conn.execute(
        "UPDATE users SET first_name = COALESCE(NULLIF(first_name, ''), "
        "trim(substr(full_name, 1, instr(full_name || ' ', ' ') - 1))), "
        "last_name = COALESCE(NULLIF(last_name, ''), "
        "trim(substr(full_name, instr(full_name || ' ', ' ') + 1)))"
    )


def notify(conn: sqlite3.Connection, user_id: int, kind: str, title: str, link: str = "") -> None:
    """Queue a notification for one user (SRS §17)."""
    conn.execute(
        "INSERT INTO notifications (user_id, kind, title, link, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, kind, title, link, utcnow()),
    )


def record_activity(
    conn: sqlite3.Connection,
    user_id: int,
    kind: str,
    summary: str,
    actor_id: int | None = None,
    link: str = "",
) -> None:
    """Append to one user's recent-activity feed."""
    conn.execute(
        "INSERT INTO activities (user_id, actor_id, kind, summary, link, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, actor_id, kind, summary, link, utcnow()),
    )

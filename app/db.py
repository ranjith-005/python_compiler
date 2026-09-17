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

-- A trainer's query or warning about an assignment the student has not
-- submitted, and the single reply the student may give back.
CREATE TABLE IF NOT EXISTS queries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    trainer_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    student_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    severity      TEXT NOT NULL DEFAULT 'note',
    message       TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    reply         TEXT,
    replied_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_queries_student ON queries(student_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_queries_assignment ON queries(assignment_id);

-- ── learning modules (reqs 14, 15) ──────────────────────────────────────
-- A module is uploaded as one .ipynb and flattened into ordered blocks:
-- markdown cells become content, code cells become practice sections the
-- student runs in place.
CREATE TABLE IF NOT EXISTS modules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trainer_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source_name TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'published',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS module_blocks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    kind      TEXT NOT NULL,          -- 'content' | 'code'
    source    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_module_blocks ON module_blocks(module_id, position);

CREATE TABLE IF NOT EXISTS module_assignments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id   INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    student_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assigned_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    assigned_at TEXT NOT NULL,
    UNIQUE (module_id, student_id)
);

-- One row per student per code block. ran_ok flips to 1 the first time the
-- student runs that block without an error, which is what progress counts.
CREATE TABLE IF NOT EXISTS module_progress (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id  INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    block_id   INTEGER NOT NULL REFERENCES module_blocks(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ran_ok     INTEGER NOT NULL DEFAULT 0,
    last_code  TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE (block_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_module_progress ON module_progress(module_id, student_id);

-- ── reopening a closed exercise (exercise reqs: deadline) ────────────────
-- Once the due date passes a student loses the editor. They do not lose the
-- exercise: they raise a request here and the trainer approves or rejects it,
-- with a message written for that student alone -- two students asking about
-- the same exercise can be answered differently, which is why the decision
-- lives on the request and not on the exercise.
CREATE TABLE IF NOT EXISTS access_requests (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id    INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    exercise_id      INTEGER NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    student_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    trainer_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message          TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',   -- pending|approved|rejected
    decision_message TEXT NOT NULL DEFAULT '',
    decided_at       TEXT,
    decided_by       INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_access_requests_trainer
    ON access_requests(trainer_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_access_requests_assignment
    ON access_requests(assignment_id, created_at DESC);
-- Only one request may be open on an assignment at a time; a decided one no
-- longer blocks the student from asking again.
CREATE UNIQUE INDEX IF NOT EXISTS idx_access_requests_one_open
    ON access_requests(assignment_id) WHERE status = 'pending';

-- ── modules, second cut: uploaded documents become editable sections ──────
-- A module now holds two revisions of the same list of sections: the trainer
-- edits 'draft', students only ever read 'published'. Publishing copies draft
-- rows over the published ones, which is what keeps a half-finished edit off
-- the student page (module req 19).
--
-- `section_key` is the identity that survives publishing. Row ids are recreated
-- on every publish, so progress keys on (module_id, section_key, student_id)
-- and therefore outlives edits, reordering and re-publishing.
CREATE TABLE IF NOT EXISTS module_sections (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id         INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    revision          TEXT NOT NULL DEFAULT 'draft',   -- 'draft' | 'published'
    section_key       TEXT NOT NULL,
    display_order     INTEGER NOT NULL DEFAULT 0,
    title             TEXT NOT NULL DEFAULT '',
    content           TEXT NOT NULL DEFAULT '',
    has_code_practice INTEGER NOT NULL DEFAULT 0,
    code_question     TEXT NOT NULL DEFAULT '',
    -- Two kinds of code, deliberately separate (module req 23):
    -- `reference_code` is the worked example lifted from the upload. The
    -- student reads it and may run it, but never edits it. `starter_code`
    -- is what their own editor opens with, and is normally empty so they
    -- write the solution themselves rather than editing ours.
    reference_code    TEXT NOT NULL DEFAULT '',
    starter_code      TEXT NOT NULL DEFAULT '',
    source_pages      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_module_sections
    ON module_sections(module_id, revision, display_order);
CREATE UNIQUE INDEX IF NOT EXISTS idx_module_sections_key
    ON module_sections(module_id, revision, section_key);

-- One row per student per section. `completed` is set by the student pressing
-- Mark as complete -- never by merely opening the section (module req 13), and
-- never by running the code (module req 22), which only records last_code so
-- the editor comes back as they left it.
CREATE TABLE IF NOT EXISTS module_section_progress (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id    INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    section_key  TEXT NOT NULL,
    student_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    completed    INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT,
    last_code    TEXT NOT NULL DEFAULT '',
    ran_ok       INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL,
    UNIQUE (module_id, section_key, student_id)
);
CREATE INDEX IF NOT EXISTS idx_module_section_progress
    ON module_section_progress(module_id, student_id);

-- Percentage is always derived from the two counts above, never stored, so it
-- cannot drift from the sections it describes. Only `last_accessed` -- which
-- nothing else knows -- is kept, for "Continue learning".
CREATE TABLE IF NOT EXISTS module_access (
    module_id     INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    student_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    last_accessed TEXT NOT NULL,
    PRIMARY KEY (module_id, student_id)
);
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


def utcnow_precise() -> str:
    """Microsecond-resolution timestamp.

    Plain `utcnow()` truncates to the second, which is too coarse to order two
    events that can land in the same second (e.g. a password-change session
    cutoff versus a token minted moments before or after it). Used only for
    `sessions_valid_from`.
    """
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


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
        _migrate_platform_columns(conn)
        _migrate_module_columns(conn)
        _migrate_section_columns(conn)
        _backfill_solution_code(conn)
        _migrate_snippets_to_notebooks(conn)
        _migrate_blocks_to_sections(conn)
        from .assignment_status import migrate_assignment_statuses

        migrate_assignment_statuses(conn)


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
        ("theme", "TEXT NOT NULL DEFAULT 'system'"),
        ("sessions_valid_from", "TEXT NOT NULL DEFAULT ''"),
        # Presence for the trainer's roster: stamped on authenticated requests.
        ("last_seen_at", "TEXT NOT NULL DEFAULT ''"),
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


def _migrate_platform_columns(conn: sqlite3.Connection) -> None:
    """Additive columns for tables in PLATFORM_SCHEMA.

    Mirrors _migrate_user_columns; the platform tables had no equivalent because
    every earlier change could be expressed in CREATE TABLE IF NOT EXISTS.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(assignments)")}
    for column, ddl in (
        ("solution_code", "TEXT NOT NULL DEFAULT ''"),
        ("last_stdin", "TEXT NOT NULL DEFAULT ''"),
    ):
        if column not in existing:
            conn.execute(f"ALTER TABLE assignments ADD COLUMN {column} {ddl}")


def _migrate_module_columns(conn: sqlite3.Connection) -> None:
    """Additive columns for `modules` once uploads became PDF/PPT/PPTX.

    The original table only recorded a source *name*, because a notebook was
    parsed once and then thrown away. The uploaded document is kept now, so the
    module has to remember what it was and where it went (module req 18).
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(modules)")}
    for column, ddl in (
        ("source_type", "TEXT NOT NULL DEFAULT ''"),
        ("source_path", "TEXT NOT NULL DEFAULT ''"),
        ("published_at", "TEXT"),
    ):
        if column not in existing:
            conn.execute(f"ALTER TABLE modules ADD COLUMN {column} {ddl}")


def _migrate_section_columns(conn: sqlite3.Connection) -> None:
    """Additive columns for `module_sections`.

    Sections used to carry one code field, and the example lifted out of the
    upload was written straight into it -- which handed the student the answer
    the moment they opened the section. `reference_code` splits the worked
    example away from the student's own editor (module req 23). Existing rows
    keep whatever is in `starter_code`; the trainer moves it across by editing
    the section, and nothing is deleted underneath them.
    """
    existing = {
        row["name"] for row in conn.execute("PRAGMA table_info(module_sections)")
    }
    if "reference_code" not in existing:
        conn.execute(
            "ALTER TABLE module_sections ADD COLUMN reference_code TEXT NOT NULL DEFAULT ''"
        )


def _migrate_blocks_to_sections(conn: sqlite3.Connection) -> None:
    """Carry notebook-era modules over to sections.

    Blocks were a flat run of content and code. A section is one topic, so each
    content block opens a section and the code block following it becomes that
    section's practice. Modules created this way are already visible to
    students, so both revisions are written and the module stays published.

    Per-block `ran_ok` becomes the section's completed flag: those students did
    the only thing the old player asked of them, and resetting their progress to
    zero would be a worse answer than carrying it across.
    """
    key = "module_blocks_to_sections_v1"
    if conn.execute("SELECT 1 FROM migrations WHERE key = ?", (key,)).fetchone():
        return
    now = utcnow()
    modules = conn.execute("SELECT id FROM modules").fetchall()
    for module in modules:
        module_id = int(module["id"])
        if conn.execute(
            "SELECT 1 FROM module_sections WHERE module_id = ?", (module_id,)
        ).fetchone():
            continue
        blocks = conn.execute(
            "SELECT id, kind, source FROM module_blocks WHERE module_id = ? ORDER BY position",
            (module_id,),
        ).fetchall()
        if not blocks:
            continue

        sections: list[dict] = []
        for block in blocks:
            source = (block["source"] or "").strip()
            if not source:
                continue
            if block["kind"] == "code":
                # A code block with no lesson above it is still a section of
                # its own; content must never be dropped (module req 12).
                if not sections or sections[-1]["has_code"]:
                    sections.append(
                        {"title": "", "content": "", "has_code": False,
                         "code": "", "block_ids": []}
                    )
                sections[-1]["has_code"] = True
                sections[-1]["code"] = source
                sections[-1]["block_ids"].append(int(block["id"]))
            else:
                sections.append(
                    {"title": "", "content": source, "has_code": False,
                     "code": "", "block_ids": []}
                )

        for order, section in enumerate(sections):
            section_key = f"legacy-{module_id}-{order}"
            title = _first_heading(section["content"]) or f"Section {order + 1}"
            for revision in ("draft", "published"):
                conn.execute(
                    "INSERT INTO module_sections (module_id, revision, section_key,"
                    " display_order, title, content, has_code_practice, code_question,"
                    " starter_code) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?)",
                    (module_id, revision, section_key, order, title, section["content"],
                     int(section["has_code"]), section["code"]),
                )
            if not section["block_ids"]:
                continue
            placeholders = ",".join("?" * len(section["block_ids"]))
            for row in conn.execute(
                f"SELECT student_id, ran_ok, last_code FROM module_progress"
                f" WHERE block_id IN ({placeholders})",
                section["block_ids"],
            ).fetchall():
                conn.execute(
                    "INSERT OR IGNORE INTO module_section_progress (module_id, section_key,"
                    " student_id, completed, completed_at, last_code, ran_ok, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (module_id, section_key, int(row["student_id"]), int(row["ran_ok"]),
                     now if row["ran_ok"] else None, row["last_code"] or "",
                     int(row["ran_ok"]), now),
                )

    conn.execute(
        "UPDATE modules SET source_type = 'ipynb' WHERE source_type = '' AND source_name != ''"
    )
    conn.execute(
        "UPDATE modules SET published_at = created_at"
        " WHERE published_at IS NULL AND status = 'published'"
    )
    conn.execute("INSERT INTO migrations (key, applied_at) VALUES (?, ?)", (key, now))


def _first_heading(text: str) -> str:
    """The first markdown heading or first short line, as a section title."""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            return line.lstrip("#").strip()[:120]
        return line[:120]
    return ""


def _backfill_solution_code(conn: sqlite3.Connection) -> None:
    """Carry each assignment's notebook code into its own solution column.

    The exercise solve surface moves off notebooks in this phase. Without this,
    every student with work in progress would open the new editor and find it
    empty.
    """
    key = "notebook_code_to_solution_v1"
    if conn.execute("SELECT 1 FROM migrations WHERE key = ?", (key,)).fetchone():
        return
    rows = conn.execute(
        "SELECT id, notebook_id FROM assignments"
        " WHERE notebook_id IS NOT NULL AND solution_code = ''"
    ).fetchall()
    for row in rows:
        cells = conn.execute(
            "SELECT source FROM cells WHERE notebook_id = ? AND cell_type = 'code'"
            " ORDER BY position",
            (row["notebook_id"],),
        ).fetchall()
        code = "\n\n".join(c["source"] for c in cells if c["source"].strip())
        if code:
            conn.execute(
                "UPDATE assignments SET solution_code = ? WHERE id = ?", (code, row["id"])
            )
    conn.execute("INSERT INTO migrations (key, applied_at) VALUES (?, ?)", (key, utcnow()))


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

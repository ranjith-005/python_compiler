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

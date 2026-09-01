"""Learning modules (reqs 14, 15, 17; student reqs 1, 2).

A trainer authors a module wherever they like -- this app's own notebook
editor, Jupyter, Colab -- and uploads the .ipynb. It is flattened once, on
upload, into an ordered list of blocks:

    markdown cell  ->  content block   (what the student reads)
    code cell      ->  code block      (what the student runs)

That is the whole of requirement 15: the trainer uploads contents, they do
not assemble a module item by item in the website.

The student player renders those blocks in order, giving each code block an
editor, a Run button and an output pane, so a topic is followed immediately
by practice the way w3schools does it (req 14).

Progress is evidence, not self-assessment: a code block counts once the
student has run it without raising (student req 2).
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from .config import settings
from .db import get_conn, notify, record_activity, utcnow
from .deps import get_current_user, require_student, require_trainer
from .schemas import AssignIn, RunIn
from .workspace import workspace_dir

router = APIRouter(prefix="/api", tags=["modules"])

# A practice snippet is a learner's first attempt at a loop; keep the leash
# short so an accidental `while True` cannot tie up a worker.
RUN_TIMEOUT_SEC = min(settings.CELL_TIMEOUT_SEC, 15)

MAX_MODULE_BYTES = 5_000_000


def _text(source) -> str:
    """A notebook cell's source is either a string or a list of lines."""
    if isinstance(source, list):
        return "".join(source)
    return source or ""


def parse_notebook(raw: bytes) -> list[tuple[str, str]]:
    """Flatten an .ipynb into ordered (kind, source) blocks.

    Raises ValueError if this is not a notebook we can read.
    """
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("That file is not a readable .ipynb notebook") from exc

    cells = doc.get("cells")
    if not isinstance(cells, list) or not cells:
        raise ValueError("That notebook has no cells")

    blocks: list[tuple[str, str]] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        kind = cell.get("cell_type")
        body = _text(cell.get("source")).strip("\n")
        if not body.strip():
            continue
        if kind == "code":
            blocks.append(("code", body))
        elif kind in ("markdown", "raw"):
            blocks.append(("content", body))

    if not blocks:
        raise ValueError("That notebook has no content")
    return blocks


def _progress(done: int, total: int) -> int:
    return round(100 * done / total) if total else 0


def _assigned(conn: sqlite3.Connection, module_id: int, student_id: int) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM module_assignments WHERE module_id = ? AND student_id = ?",
            (module_id, student_id),
        ).fetchone()
    )


# ─────────────────────────────── trainer side ───────────────────────────────


@router.post("/modules", status_code=status.HTTP_201_CREATED)
async def upload_module(
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    user: sqlite3.Row = Depends(require_trainer),
) -> dict:
    """Upload one .ipynb and store it as a module (reqs 14, 15)."""
    raw = await file.read()
    if len(raw) > MAX_MODULE_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That notebook is too large")
    try:
        blocks = parse_notebook(raw)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    name = (title or "").strip() or (file.filename or "Module").rsplit(".", 1)[0]
    now = utcnow()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO modules (trainer_id, title, description, source_name, status,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, 'published', ?, ?)",
            (int(user["id"]), name, description.strip(), file.filename or "", now, now),
        )
        module_id = int(cur.lastrowid)
        for position, (kind, source) in enumerate(blocks):
            conn.execute(
                "INSERT INTO module_blocks (module_id, position, kind, source)"
                " VALUES (?, ?, ?, ?)",
                (module_id, position, kind, source),
            )
        record_activity(
            conn,
            int(user["id"]),
            "created",
            f'Uploaded the module "{name}"',
            int(user["id"]),
            "/trainer/modules",
        )

    code_blocks = sum(1 for kind, _ in blocks if kind == "code")
    return {"id": module_id, "title": name, "blocks": len(blocks), "code_blocks": code_blocks}


@router.post("/modules/{module_id}/assign")
def assign_module(
    module_id: int, body: AssignIn, user: sqlite3.Row = Depends(require_trainer)
) -> dict:
    """Give a module to students (req 15)."""
    trainer_id = int(user["id"])
    now = utcnow()
    with get_conn() as conn:
        module = conn.execute(
            "SELECT * FROM modules WHERE id = ? AND trainer_id = ?", (module_id, trainer_id)
        ).fetchone()
        if not module:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such module")

        valid = {
            int(r["id"])
            for r in conn.execute("SELECT id FROM users WHERE role = 'student' AND is_active = 1")
        }
        title = module["title"]
        assigned = 0
        for student_id in dict.fromkeys(body.assign_to):
            if int(student_id) not in valid:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO module_assignments (module_id, student_id, assigned_by,"
                " assigned_at) VALUES (?, ?, ?, ?)",
                (module_id, student_id, trainer_id, now),
            )
            assigned += 1
            notify(conn, student_id, "assigned", f"New module: {title}", "/student/modules")
    return {"id": module_id, "assigned": assigned}


@router.delete("/modules/{module_id}")
def delete_module(module_id: int, user: sqlite3.Row = Depends(require_trainer)) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM modules WHERE id = ? AND trainer_id = ?", (module_id, int(user["id"]))
        )
        if not cur.rowcount:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such module")
    return {"ok": True}


# ─────────────────────────── both roles read these ──────────────────────────


@router.get("/modules")
def list_modules(user: sqlite3.Row = Depends(get_current_user)) -> list[dict]:
    """A trainer's own modules, or the ones a student has been given."""
    uid = int(user["id"])
    trainer = user["role"] == "trainer"
    with get_conn() as conn:
        if trainer:
            rows = conn.execute(
                "SELECT m.*, (SELECT COUNT(*) FROM module_assignments a WHERE a.module_id = m.id)"
                "        AS assigned"
                " FROM modules m WHERE m.trainer_id = ? ORDER BY m.updated_at DESC",
                (uid,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT m.*, a.assigned_at FROM modules m"
                " JOIN module_assignments a ON a.module_id = m.id"
                " WHERE a.student_id = ? ORDER BY a.assigned_at DESC",
                (uid,),
            ).fetchall()

        result = []
        for row in rows:
            item = dict(row)
            total = conn.execute(
                "SELECT COUNT(*) FROM module_blocks WHERE module_id = ? AND kind = 'code'",
                (row["id"],),
            ).fetchone()[0]
            item["code_blocks"] = total
            if trainer:
                item["progress"] = None
            else:
                done = conn.execute(
                    "SELECT COUNT(*) FROM module_progress"
                    " WHERE module_id = ? AND student_id = ? AND ran_ok = 1",
                    (row["id"], uid),
                ).fetchone()[0]
                item["completed_blocks"] = done
                item["progress"] = _progress(done, total)
            result.append(item)
    return result


@router.get("/modules/{module_id}")
def module_detail(module_id: int, user: sqlite3.Row = Depends(get_current_user)) -> dict:
    """The module's blocks, plus progress for whoever is asking (reqs 14, 17)."""
    uid = int(user["id"])
    trainer = user["role"] == "trainer"
    with get_conn() as conn:
        module = conn.execute("SELECT * FROM modules WHERE id = ?", (module_id,)).fetchone()
        if not module:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such module")
        if trainer:
            if int(module["trainer_id"]) != uid:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "No such module")
        elif not _assigned(conn, module_id, uid):
            # A module nobody gave you does not exist as far as you are concerned.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such module")

        blocks = [
            dict(b)
            for b in conn.execute(
                "SELECT id, position, kind, source FROM module_blocks"
                " WHERE module_id = ? ORDER BY position",
                (module_id,),
            )
        ]
        total = sum(1 for b in blocks if b["kind"] == "code")

        item = dict(module)
        item["blocks"] = blocks
        item["code_blocks"] = total

        if trainer:
            students = []
            for row in conn.execute(
                "SELECT u.id, u.full_name, u.email, a.assigned_at FROM module_assignments a"
                " JOIN users u ON u.id = a.student_id WHERE a.module_id = ?"
                " ORDER BY u.full_name COLLATE NOCASE",
                (module_id,),
            ):
                done = conn.execute(
                    "SELECT COUNT(*) FROM module_progress"
                    " WHERE module_id = ? AND student_id = ? AND ran_ok = 1",
                    (module_id, row["id"]),
                ).fetchone()[0]
                students.append(
                    {**dict(row), "completed_blocks": done, "progress": _progress(done, total)}
                )
            item["students"] = students
        else:
            progress = {
                int(r["block_id"]): dict(r)
                for r in conn.execute(
                    "SELECT block_id, ran_ok, last_code FROM module_progress"
                    " WHERE module_id = ? AND student_id = ?",
                    (module_id, uid),
                )
            }
            done = 0
            for block in blocks:
                if block["kind"] != "code":
                    continue
                mine = progress.get(block["id"])
                block["ran_ok"] = bool(mine and mine["ran_ok"])
                block["last_code"] = (mine or {}).get("last_code") or block["source"]
                done += 1 if block["ran_ok"] else 0
            item["completed_blocks"] = done
            item["progress"] = _progress(done, total)
    return item


# ──────────────────────────── the student runs code ─────────────────────────


@router.post("/modules/{module_id}/blocks/{block_id}/run")
def run_block(
    module_id: int,
    block_id: int,
    body: RunIn,
    user: sqlite3.Row = Depends(require_student),
) -> dict:
    """Run one practice snippet and record progress (req 14, student req 2).

    Each run is a fresh subprocess: a learning snippet should behave the same
    however many times it is run, and nothing a student writes here can leak
    into the next block.
    """
    student_id = int(user["id"])
    with get_conn() as conn:
        block = conn.execute(
            "SELECT b.* FROM module_blocks b WHERE b.id = ? AND b.module_id = ?",
            (block_id, module_id),
        ).fetchone()
        if not block or not _assigned(conn, module_id, student_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such module block")
        if block["kind"] != "code":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "That block is not a code section")

    code = body.code
    cwd = workspace_dir(student_id)
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", code],
            input="",
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_SEC,
            cwd=str(cwd),
        )
        stdout, stderr, ok = proc.stdout, proc.stderr, proc.returncode == 0
    except subprocess.TimeoutExpired:
        stdout, stderr, ok = "", f"Timed out after {RUN_TIMEOUT_SEC}s.", False

    now = utcnow()
    with get_conn() as conn:
        # ran_ok only ever climbs: having once got it right should not be
        # undone by experimenting afterwards.
        conn.execute(
            "INSERT INTO module_progress (module_id, block_id, student_id, ran_ok, last_code,"
            " updated_at) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(block_id, student_id) DO UPDATE SET"
            "   ran_ok = MAX(ran_ok, excluded.ran_ok),"
            "   last_code = excluded.last_code,"
            "   updated_at = excluded.updated_at",
            (module_id, block_id, student_id, int(ok), code, now),
        )
        total = conn.execute(
            "SELECT COUNT(*) FROM module_blocks WHERE module_id = ? AND kind = 'code'",
            (module_id,),
        ).fetchone()[0]
        done = conn.execute(
            "SELECT COUNT(*) FROM module_progress"
            " WHERE module_id = ? AND student_id = ? AND ran_ok = 1",
            (module_id, student_id),
        ).fetchone()[0]

    return {
        "ok": ok,
        "stdout": stdout[-8000:],
        "stderr": stderr[-4000:],
        "completed_blocks": done,
        "progress": _progress(done, total),
    }

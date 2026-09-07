"""Learning modules (module reqs 1-30; reqs 14, 15, 17; student reqs 1, 2).

A trainer uploads the learning material itself -- a PDF, or a PowerPoint deck --
and the whole document is turned into ordered sections:

    one logical topic  ->  one section: a title and its content
    a practical topic  ->  that section also gets code practice

Sections exist in two revisions. The trainer edits `draft`; students only ever
read `published`. Publishing copies the draft over the published rows, so an
unfinished edit cannot reach a student mid-lesson (module req 19).

Progress is per student, per section, and stored against the section's stable
`section_key` rather than its row id -- so editing, reordering, adding, or
re-publishing a module leaves a student's completed sections exactly where they
were (module reqs 10, 11, 15, 17).

Two rules this module is careful about, because they are easy to get wrong:

  * Content is never conditional on code. A section without code practice still
    renders its content (module reqs 2, 20).
  * Nothing marks a section complete except the student saying so. Opening it
    does not (req 13); running its code does not (req 22).
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from . import documents
from .config import settings
from .db import connect, get_conn, notify, record_activity, utcnow
from .deps import get_current_user, require_student, require_trainer
from .documents import DocumentError
from .names import display_name
from .schemas import (
    AssignIn,
    ModuleMetaIn,
    RunIn,
    SectionCompleteIn,
    SectionIn,
    SectionMoveIn,
    SectionPatch,
    SectionSplitIn,
)
from .workspace import workspace_dir

router = APIRouter(prefix="/api", tags=["modules"])

# A practice snippet is a learner's first attempt at a loop; keep the leash
# short so an accidental `while True` cannot tie up a worker.
RUN_TIMEOUT_SEC = min(settings.CELL_TIMEOUT_SEC, 15)


def _progress(done: int, total: int) -> int:
    return round(100 * done / total) if total else 0


def _display(row: dict, name_key: str = "full_name", email_key: str = "email") -> str:
    """`display_name` for a joined row that carries only a name and an email."""
    return display_name(
        {
            "full_name": row.get(name_key) or "",
            "first_name": "",
            "last_name": "",
            "email": row.get(email_key) or "",
        }
    )


def _assigned(conn: sqlite3.Connection, module_id: int, student_id: int) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM module_assignments WHERE module_id = ? AND student_id = ?",
            (module_id, student_id),
        ).fetchone()
    )


def _own_module(conn: sqlite3.Connection, module_id: int, trainer_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM modules WHERE id = ? AND trainer_id = ?", (module_id, trainer_id)
    ).fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such module")
    return row


def _touch(conn: sqlite3.Connection, module_id: int) -> None:
    conn.execute("UPDATE modules SET updated_at = ? WHERE id = ?", (utcnow(), module_id))


def _draft_sections(conn: sqlite3.Connection, module_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM module_sections WHERE module_id = ? AND revision = 'draft'"
        " ORDER BY display_order, id",
        (module_id,),
    ).fetchall()


def _renumber(conn: sqlite3.Connection, module_id: int) -> None:
    """Close any gaps `display_order` picked up from a delete or a move."""
    for order, row in enumerate(_draft_sections(conn, module_id)):
        if int(row["display_order"]) != order:
            conn.execute(
                "UPDATE module_sections SET display_order = ? WHERE id = ?",
                (order, int(row["id"])),
            )


def _draft_section(conn: sqlite3.Connection, module_id: int, section_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM module_sections WHERE id = ? AND module_id = ? AND revision = 'draft'",
        (section_id, module_id),
    ).fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such section")
    return row


def _insert_section(conn: sqlite3.Connection, module_id: int, order: int, *,
                    title: str = "", content: str = "", has_code: bool = False,
                    question: str = "", starter: str = "", pages: str = "",
                    revision: str = "draft", key: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO module_sections (module_id, revision, section_key, display_order,"
        " title, content, has_code_practice, code_question, starter_code, source_pages)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (module_id, revision, key or uuid.uuid4().hex, order, title, content,
         int(has_code), question, starter, pages),
    )
    return int(cur.lastrowid)


# ══════════════════════ upload: processed in the background ════════════════
# Module req 17: a 200-page PDF takes real time to read, and the page must not
# sit frozen while it happens. The upload returns a job id straight away and the
# worker publishes each step it actually reaches -- the frontend reports the
# stage the job is really in, never a guess on a timer.

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()
_JOB_KEEP = 200


def _set_job(job_id: str, **fields) -> None:
    with _JOBS_LOCK:
        job = _JOBS.setdefault(job_id, {})
        job.update(fields)


def _get_job(job_id: str) -> dict | None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def _new_job() -> str:
    job_id = uuid.uuid4().hex
    with _JOBS_LOCK:
        # Keep the map from growing without bound over a long uptime.
        if len(_JOBS) >= _JOB_KEEP:
            for stale in sorted(_JOBS, key=lambda k: _JOBS[k].get("started_at", ""))[:50]:
                _JOBS.pop(stale, None)
        _JOBS[job_id] = {
            "state": "running",
            "step": "upload",
            "message": "Uploading learning material…",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "module_id": None,
        }
    return job_id


def _process_upload(job_id: str, raw: bytes, suffix: str, filename: str,
                    title: str, description: str, trainer_id: int,
                    trainer_label: str) -> None:
    """Read the document, build sections, save the draft. Runs off-thread."""
    try:
        _set_job(job_id, step="extract", message="Extracting content…")
        units = documents.extract_units(raw, suffix)

        _set_job(job_id, step="topics", message="Identifying topics…")
        sections = documents.build_sections(units)
        if not sections:
            raise DocumentError("No learning content could be read from that file.")

        _set_job(job_id, step="sections", message="Creating sections…")
        now = utcnow()
        name = title.strip() or (filename or "Module").rsplit(".", 1)[0]

        # One connection of its own: this is a different thread, and sqlite3
        # connections are not shared across threads.
        conn = connect()
        try:
            cur = conn.execute(
                "INSERT INTO modules (trainer_id, title, description, source_name,"
                " source_type, source_path, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, '', 'draft', ?, ?)",
                (trainer_id, name, description.strip(), filename or "",
                 suffix.lstrip("."), now, now),
            )
            module_id = int(cur.lastrowid)

            # Keep the original file with the module (module req 18).
            settings.MODULE_SOURCE_ROOT.mkdir(parents=True, exist_ok=True)
            stored = settings.MODULE_SOURCE_ROOT / f"{module_id}{suffix}"
            stored.write_bytes(raw)
            conn.execute(
                "UPDATE modules SET source_path = ? WHERE id = ?", (str(stored), module_id)
            )

            for order, section in enumerate(sections):
                _insert_section(
                    conn, module_id, order,
                    title=section.title, content=section.content,
                    has_code=section.has_code_practice, question=section.code_question,
                    starter=section.starter_code, pages=section.source_pages,
                )
            record_activity(
                conn, trainer_id, "created",
                f'{trainer_label} uploaded the module "{name}"',
                trainer_id, "/trainer/modules",
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        practice = sum(1 for s in sections if s.has_code_practice)
        _set_job(
            job_id, state="done", step="done", module_id=module_id, title=name,
            units=len(units), sections=len(sections), code_sections=practice,
            message="Your module draft is ready for review.",
        )
    except DocumentError as exc:
        _set_job(job_id, state="error", step="error", message=str(exc))
    except Exception as exc:  # pragma: no cover - unexpected, still must report
        _set_job(job_id, state="error", step="error",
                 message=f"That file could not be processed ({exc.__class__.__name__}).")


@router.post("/modules", status_code=status.HTTP_202_ACCEPTED)
async def upload_module(
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    user: sqlite3.Row = Depends(require_trainer),
) -> dict:
    """Accept one PDF/PPT/PPTX and start processing it (module reqs 1-4)."""
    suffix = documents.suffix_of(file.filename or "")
    if not suffix:
        # Backend validation, mirroring the accept="" on the input (req 3).
        raise HTTPException(status.HTTP_400_BAD_REQUEST, documents.UNSUPPORTED_MESSAGE)

    raw = await file.read()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That file is empty.")
    if len(raw) > settings.MAX_MODULE_BYTES:
        limit = settings.MAX_MODULE_BYTES // 1_000_000
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"That file is larger than {limit} MB."
        )

    job_id = _new_job()
    thread = threading.Thread(
        target=_process_upload,
        args=(job_id, raw, suffix, file.filename or "", title, description,
              int(user["id"]), display_name(user)),
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id, "state": "running"}


@router.get("/modules/jobs/{job_id}")
def upload_status(job_id: str, user: sqlite3.Row = Depends(require_trainer)) -> dict:
    job = _get_job(job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such upload")
    return job


# ─────────────────────────── trainer: edit the draft ────────────────────────


@router.patch("/modules/{module_id}")
def update_module(
    module_id: int, body: ModuleMetaIn, user: sqlite3.Row = Depends(require_trainer)
) -> dict:
    """Rename a module or change its description (module req 13)."""
    with get_conn() as conn:
        _own_module(conn, module_id, int(user["id"]))
        title = body.title.strip()
        if not title:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A module needs a name.")
        conn.execute(
            "UPDATE modules SET title = ?, description = ?, updated_at = ? WHERE id = ?",
            (title, body.description.strip(), utcnow(), module_id),
        )
    return {"id": module_id, "title": title, "description": body.description.strip()}


@router.post("/modules/{module_id}/sections", status_code=status.HTTP_201_CREATED)
def add_section(
    module_id: int, body: SectionIn, user: sqlite3.Row = Depends(require_trainer)
) -> dict:
    with get_conn() as conn:
        _own_module(conn, module_id, int(user["id"]))
        order = len(_draft_sections(conn, module_id))
        section_id = _insert_section(
            conn, module_id, order,
            title=body.title.strip() or f"Section {order + 1}",
            content=body.content, has_code=body.has_code_practice,
            question=body.code_question, starter=body.starter_code,
        )
        _touch(conn, module_id)
    return {"id": section_id, "display_order": order}


@router.patch("/modules/{module_id}/sections/{section_id}")
def update_section(
    module_id: int, section_id: int, body: SectionPatch,
    user: sqlite3.Row = Depends(require_trainer),
) -> dict:
    """Edit one draft section. Omitted fields keep their current value."""
    with get_conn() as conn:
        _own_module(conn, module_id, int(user["id"]))
        _draft_section(conn, module_id, section_id)

        updates: list[tuple[str, object]] = []
        if body.title is not None:
            updates.append(("title", body.title.strip()))
        if body.content is not None:
            updates.append(("content", body.content))
        if body.has_code_practice is not None:
            updates.append(("has_code_practice", int(body.has_code_practice)))
        if body.code_question is not None:
            updates.append(("code_question", body.code_question))
        if body.starter_code is not None:
            updates.append(("starter_code", body.starter_code))
        if updates:
            clause = ", ".join(f"{name} = ?" for name, _ in updates)
            conn.execute(
                f"UPDATE module_sections SET {clause} WHERE id = ?",
                [value for _, value in updates] + [section_id],
            )
            _touch(conn, module_id)
        row = _draft_section(conn, module_id, section_id)
    return dict(row)


@router.delete("/modules/{module_id}/sections/{section_id}")
def delete_section(
    module_id: int, section_id: int, user: sqlite3.Row = Depends(require_trainer)
) -> dict:
    with get_conn() as conn:
        _own_module(conn, module_id, int(user["id"]))
        _draft_section(conn, module_id, section_id)
        conn.execute("DELETE FROM module_sections WHERE id = ?", (section_id,))
        _renumber(conn, module_id)
        _touch(conn, module_id)
    return {"ok": True}


@router.post("/modules/{module_id}/sections/{section_id}/move")
def move_section(
    module_id: int, section_id: int, body: SectionMoveIn,
    user: sqlite3.Row = Depends(require_trainer),
) -> dict:
    """Swap one section with its neighbour (module req 13)."""
    with get_conn() as conn:
        _own_module(conn, module_id, int(user["id"]))
        rows = _draft_sections(conn, module_id)
        index = next((i for i, r in enumerate(rows) if int(r["id"]) == section_id), None)
        if index is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such section")
        target = index - 1 if body.direction == "up" else index + 1
        if not 0 <= target < len(rows):
            return {"ok": True, "moved": False}
        rows = list(rows)
        rows[index], rows[target] = rows[target], rows[index]
        for order, row in enumerate(rows):
            conn.execute(
                "UPDATE module_sections SET display_order = ? WHERE id = ?",
                (order, int(row["id"])),
            )
        _touch(conn, module_id)
    return {"ok": True, "moved": True}


@router.post("/modules/{module_id}/sections/{section_id}/merge")
def merge_section(
    module_id: int, section_id: int, user: sqlite3.Row = Depends(require_trainer)
) -> dict:
    """Fold the next section into this one (module req 13).

    Content is concatenated in order, and code practice survives if either half
    had it -- merging two topics must not silently drop the exercise from one.
    """
    with get_conn() as conn:
        _own_module(conn, module_id, int(user["id"]))
        rows = _draft_sections(conn, module_id)
        index = next((i for i, r in enumerate(rows) if int(r["id"]) == section_id), None)
        if index is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such section")
        if index + 1 >= len(rows):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "This is the last section; there is nothing "
                "after it to merge in."
            )
        first, second = rows[index], rows[index + 1]

        content = "\n\n".join(
            part for part in (first["content"], second["title"], second["content"]) if part
        )
        has_code = bool(first["has_code_practice"]) or bool(second["has_code_practice"])
        question = first["code_question"] or second["code_question"]
        starter = first["starter_code"] or second["starter_code"]
        pages = " + ".join(p for p in (first["source_pages"], second["source_pages"]) if p)

        conn.execute(
            "UPDATE module_sections SET content = ?, has_code_practice = ?,"
            " code_question = ?, starter_code = ?, source_pages = ? WHERE id = ?",
            (content, int(has_code), question, starter, pages, int(first["id"])),
        )
        conn.execute("DELETE FROM module_sections WHERE id = ?", (int(second["id"]),))
        _renumber(conn, module_id)
        _touch(conn, module_id)
    return {"ok": True, "id": int(first["id"])}


@router.post("/modules/{module_id}/sections/{section_id}/split")
def split_section(
    module_id: int, section_id: int, body: SectionSplitIn,
    user: sqlite3.Row = Depends(require_trainer),
) -> dict:
    """Cut one section in two at a line of its content (module req 13).

    The second half is a new section with a new key, so nobody's progress on the
    first half is disturbed.
    """
    with get_conn() as conn:
        _own_module(conn, module_id, int(user["id"]))
        row = _draft_section(conn, module_id, section_id)
        lines = (row["content"] or "").splitlines()
        if not 1 <= body.at_line < len(lines):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Choose a line between 1 and {max(len(lines) - 1, 1)} to split at.",
            )
        head = "\n".join(lines[: body.at_line]).strip()
        tail = "\n".join(lines[body.at_line:]).strip()

        order = int(row["display_order"])
        # Everything after this section shifts down one to make room.
        conn.execute(
            "UPDATE module_sections SET display_order = display_order + 1"
            " WHERE module_id = ? AND revision = 'draft' AND display_order > ?",
            (module_id, order),
        )
        conn.execute("UPDATE module_sections SET content = ? WHERE id = ?", (head, section_id))
        new_id = _insert_section(
            conn, module_id, order + 1,
            title=body.title.strip() or f"{row['title']} (continued)",
            content=tail,
            # The practice belongs to the half the trainer keeps it on; they can
            # move it after the split.
            has_code=False, pages=row["source_pages"],
        )
        _renumber(conn, module_id)
        _touch(conn, module_id)
    return {"ok": True, "id": new_id}


@router.post("/modules/{module_id}/publish")
def publish_module(module_id: int, user: sqlite3.Row = Depends(require_trainer)) -> dict:
    """Copy the draft over the published revision (module reqs 15, 19).

    Until this runs, a student sees the previous published version -- or, for a
    module never published, nothing at all.
    """
    with get_conn() as conn:
        _own_module(conn, module_id, int(user["id"]))
        drafts = _draft_sections(conn, module_id)
        if not drafts:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "This module has no sections to publish."
            )
        conn.execute(
            "DELETE FROM module_sections WHERE module_id = ? AND revision = 'published'",
            (module_id,),
        )
        for order, row in enumerate(drafts):
            _insert_section(
                conn, module_id, order, revision="published", key=row["section_key"],
                title=row["title"], content=row["content"],
                has_code=bool(row["has_code_practice"]), question=row["code_question"],
                starter=row["starter_code"], pages=row["source_pages"],
            )
        now = utcnow()
        conn.execute(
            "UPDATE modules SET status = 'published', published_at = ?, updated_at = ?"
            " WHERE id = ?",
            (now, now, module_id),
        )
        for row in conn.execute(
            "SELECT student_id FROM module_assignments WHERE module_id = ?", (module_id,)
        ).fetchall():
            notify(conn, int(row["student_id"]), "assigned",
                   "A module you were given has been updated", "/student/modules")
    return {"id": module_id, "status": "published", "sections": len(drafts)}


@router.post("/modules/{module_id}/unpublish")
def unpublish_module(module_id: int, user: sqlite3.Row = Depends(require_trainer)) -> dict:
    """Take a module back off the student pages while it is reworked."""
    with get_conn() as conn:
        _own_module(conn, module_id, int(user["id"]))
        conn.execute(
            "DELETE FROM module_sections WHERE module_id = ? AND revision = 'published'",
            (module_id,),
        )
        conn.execute(
            "UPDATE modules SET status = 'draft', updated_at = ? WHERE id = ?",
            (utcnow(), module_id),
        )
    return {"id": module_id, "status": "draft"}


@router.post("/modules/{module_id}/assign")
def assign_module(
    module_id: int, body: AssignIn, user: sqlite3.Row = Depends(require_trainer)
) -> dict:
    """Give a module to students (req 15)."""
    trainer_id = int(user["id"])
    now = utcnow()
    with get_conn() as conn:
        module = _own_module(conn, module_id, trainer_id)
        valid = {
            int(r["id"])
            for r in conn.execute("SELECT id FROM users WHERE role = 'student' AND is_active = 1")
        }
        title = module["title"]
        actor = display_name(user)
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
            # Requirement: the student's history names the trainer who gave
            # them the module, the same way an assigned exercise does.
            record_activity(
                conn, student_id, "assigned",
                f'{actor} assigned the module "{title}"', trainer_id, "/student/modules",
            )
    return {"id": module_id, "assigned": assigned}


@router.delete("/modules/{module_id}")
def delete_module(module_id: int, user: sqlite3.Row = Depends(require_trainer)) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT source_path FROM modules WHERE id = ? AND trainer_id = ?",
            (module_id, int(user["id"])),
        ).fetchone()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such module")
        conn.execute("DELETE FROM modules WHERE id = ?", (module_id,))
    # The row is gone either way; a stored file we cannot remove is a stray
    # file, not a failed delete, so it must not turn into an error response.
    source = (row["source_path"] or "").strip()
    if source:
        try:
            os.remove(source)
        except OSError:
            pass
    return {"ok": True}


# ─────────────────────────── both roles read these ──────────────────────────


def _counts(conn: sqlite3.Connection, module_id: int, student_id: int) -> tuple[int, int]:
    """(total published sections, sections this student has completed)."""
    total = conn.execute(
        "SELECT COUNT(*) FROM module_sections WHERE module_id = ? AND revision = 'published'",
        (module_id,),
    ).fetchone()[0]
    done = conn.execute(
        "SELECT COUNT(*) FROM module_section_progress p"
        " WHERE p.module_id = ? AND p.student_id = ? AND p.completed = 1"
        "   AND EXISTS (SELECT 1 FROM module_sections s WHERE s.module_id = p.module_id"
        "               AND s.revision = 'published' AND s.section_key = p.section_key)",
        (module_id, student_id),
    ).fetchone()[0]
    return total, done


@router.get("/modules")
def list_modules(user: sqlite3.Row = Depends(get_current_user)) -> list[dict]:
    """A trainer's own modules, or the published ones a student was given.

    Module req 18: a student's list is filtered to modules that are both
    assigned to them and published. A draft is invisible to them.
    """
    uid = int(user["id"])
    trainer = user["role"] == "trainer"
    with get_conn() as conn:
        if trainer:
            rows = conn.execute(
                "SELECT m.*,"
                " (SELECT COUNT(*) FROM module_assignments a WHERE a.module_id = m.id)"
                "   AS assigned,"
                " (SELECT COUNT(*) FROM module_sections s WHERE s.module_id = m.id"
                "    AND s.revision = 'draft') AS sections,"
                " (SELECT COUNT(*) FROM module_sections s WHERE s.module_id = m.id"
                "    AND s.revision = 'draft' AND s.has_code_practice = 1) AS code_sections"
                " FROM modules m WHERE m.trainer_id = ? ORDER BY m.updated_at DESC",
                (uid,),
            ).fetchall()
            return [dict(row) | {"progress": None} for row in rows]

        rows = conn.execute(
            "SELECT m.*, a.assigned_at, acc.last_accessed FROM modules m"
            " JOIN module_assignments a ON a.module_id = m.id AND a.student_id = ?"
            " LEFT JOIN module_access acc ON acc.module_id = m.id AND acc.student_id = ?"
            " WHERE m.status = 'published'"
            " ORDER BY a.assigned_at DESC",
            (uid, uid),
        ).fetchall()

        result = []
        for row in rows:
            total, done = _counts(conn, int(row["id"]), uid)
            # Where to send "Continue learning": the first section they have
            # not ticked, or the start if they have finished (req 15).
            nxt = conn.execute(
                "SELECT s.id FROM module_sections s"
                " WHERE s.module_id = ? AND s.revision = 'published'"
                "   AND NOT EXISTS (SELECT 1 FROM module_section_progress p"
                "                   WHERE p.module_id = s.module_id"
                "                     AND p.section_key = s.section_key"
                "                     AND p.student_id = ? AND p.completed = 1)"
                " ORDER BY s.display_order LIMIT 1",
                (int(row["id"]), uid),
            ).fetchone()
            result.append(
                dict(row)
                | {
                    "sections": total,
                    "completed_sections": done,
                    "progress": _progress(done, total),
                    "completed": total > 0 and done == total,
                    "next_section_id": int(nxt["id"]) if nxt else None,
                }
            )
    return result


@router.get("/modules/{module_id}")
def module_detail(module_id: int, user: sqlite3.Row = Depends(get_current_user)) -> dict:
    """One module: its sections, plus progress for whoever is asking.

    The trainer gets the draft (what they are editing). The student gets the
    published revision and only if it is assigned to them (module reqs 18, 19).
    """
    uid = int(user["id"])
    trainer = user["role"] == "trainer"
    with get_conn() as conn:
        module = conn.execute("SELECT * FROM modules WHERE id = ?", (module_id,)).fetchone()
        if not module:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such module")

        if trainer:
            if int(module["trainer_id"]) != uid:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "No such module")
            sections = [dict(r) for r in _draft_sections(conn, module_id)]
            item = dict(module)
            item["sections"] = sections
            item["section_count"] = len(sections)
            item["code_sections"] = sum(1 for s in sections if s["has_code_practice"])
            item["published_count"] = conn.execute(
                "SELECT COUNT(*) FROM module_sections WHERE module_id = ?"
                " AND revision = 'published'",
                (module_id,),
            ).fetchone()[0]

            total_published = item["published_count"]
            students = []
            for row in conn.execute(
                "SELECT u.id, u.full_name, u.email, a.assigned_at FROM module_assignments a"
                " JOIN users u ON u.id = a.student_id WHERE a.module_id = ?"
                " ORDER BY u.full_name COLLATE NOCASE",
                (module_id,),
            ):
                _, done = _counts(conn, module_id, int(row["id"]))
                row_dict = dict(row)
                students.append(
                    row_dict
                    | {
                        "completed_sections": done,
                        "total_sections": total_published,
                        "progress": _progress(done, total_published),
                        "display": _display(row_dict),
                    }
                )
            item["students"] = students
            return item

        # ── the student's view ──────────────────────────────────────────────
        if module["status"] != "published" or not _assigned(conn, module_id, uid):
            # A module nobody gave you does not exist as far as you are
            # concerned -- and neither does one still in draft.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such module")

        rows = conn.execute(
            "SELECT * FROM module_sections WHERE module_id = ? AND revision = 'published'"
            " ORDER BY display_order, id",
            (module_id,),
        ).fetchall()
        progress = {
            r["section_key"]: dict(r)
            for r in conn.execute(
                "SELECT section_key, completed, completed_at, last_code, ran_ok"
                " FROM module_section_progress WHERE module_id = ? AND student_id = ?",
                (module_id, uid),
            )
        }

        sections = []
        done = 0
        for row in rows:
            mine = progress.get(row["section_key"]) or {}
            completed = bool(mine.get("completed"))
            done += 1 if completed else 0
            sections.append(
                {
                    "id": int(row["id"]),
                    "title": row["title"],
                    "content": row["content"],
                    "has_code_practice": bool(row["has_code_practice"]),
                    "code_question": row["code_question"],
                    # The editor comes back exactly as the student left it.
                    "starter_code": mine.get("last_code") or row["starter_code"],
                    "completed": completed,
                    "completed_at": mine.get("completed_at"),
                    "ran_ok": bool(mine.get("ran_ok")),
                }
            )

        conn.execute(
            "INSERT INTO module_access (module_id, student_id, last_accessed)"
            " VALUES (?, ?, ?) ON CONFLICT(module_id, student_id)"
            " DO UPDATE SET last_accessed = excluded.last_accessed",
            (module_id, uid, utcnow()),
        )

        total = len(sections)
        return dict(module) | {
            "sections": sections,
            "section_count": total,
            "completed_sections": done,
            "progress": _progress(done, total),
            "completed": total > 0 and done == total,
        }


# ──────────────────────────── the student works ─────────────────────────────


def _student_section(conn: sqlite3.Connection, module_id: int, section_id: int,
                     student_id: int) -> sqlite3.Row:
    """One published section of a module this student actually has."""
    module = conn.execute(
        "SELECT status FROM modules WHERE id = ?", (module_id,)
    ).fetchone()
    if not module or module["status"] != "published" or not _assigned(conn, module_id, student_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such module section")
    row = conn.execute(
        "SELECT * FROM module_sections WHERE id = ? AND module_id = ? AND revision = 'published'",
        (section_id, module_id),
    ).fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such module section")
    return row


@router.post("/modules/{module_id}/sections/{section_id}/run")
def run_section(
    module_id: int, section_id: int, body: RunIn,
    user: sqlite3.Row = Depends(require_student),
) -> dict:
    """Run one section's practice snippet (module reqs 5, 6, 7).

    Each run is a fresh subprocess, and the result is returned to this section
    alone: nothing here can reach another section's editor, output or state.

    Running does NOT complete the section (module req 22). It only stores the
    code, so the editor comes back as the student left it.
    """
    student_id = int(user["id"])
    with get_conn() as conn:
        section = _student_section(conn, module_id, section_id, student_id)
        if not section["has_code_practice"]:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "This section has no code practice."
            )
        section_key = section["section_key"]

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
        conn.execute(
            "INSERT INTO module_section_progress (module_id, section_key, student_id,"
            " completed, last_code, ran_ok, updated_at) VALUES (?, ?, ?, 0, ?, ?, ?)"
            " ON CONFLICT(module_id, section_key, student_id) DO UPDATE SET"
            "   last_code = excluded.last_code,"
            "   ran_ok = MAX(module_section_progress.ran_ok, excluded.ran_ok),"
            "   updated_at = excluded.updated_at",
            (module_id, section_key, student_id, code, int(ok), now),
        )
        total, done = _counts(conn, module_id, student_id)

    return {
        "ok": ok,
        "stdout": stdout[-8000:],
        "stderr": stderr[-4000:],
        "completed_sections": done,
        "total_sections": total,
        "progress": _progress(done, total),
    }


@router.post("/modules/{module_id}/sections/{section_id}/complete")
def complete_section(
    module_id: int, section_id: int, body: SectionCompleteIn,
    user: sqlite3.Row = Depends(require_student),
) -> dict:
    """Mark one section complete, or undo it (module reqs 9, 12, 21).

    This is the only thing that moves the progress bar. The section's content
    stays exactly as available afterwards as it was before (module req 27).
    """
    student_id = int(user["id"])
    now = utcnow()
    with get_conn() as conn:
        section = _student_section(conn, module_id, section_id, student_id)
        conn.execute(
            "INSERT INTO module_section_progress (module_id, section_key, student_id,"
            " completed, completed_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(module_id, section_key, student_id) DO UPDATE SET"
            "   completed = excluded.completed,"
            "   completed_at = excluded.completed_at,"
            "   updated_at = excluded.updated_at",
            (module_id, section["section_key"], student_id, int(body.completed),
             now if body.completed else None, now),
        )
        total, done = _counts(conn, module_id, student_id)
        if body.completed and total and done == total:
            title = conn.execute(
                "SELECT title FROM modules WHERE id = ?", (module_id,)
            ).fetchone()["title"]
            record_activity(
                conn, student_id, "completed",
                f'Completed the module "{title}"', student_id, "/student/modules",
            )
    return {
        "id": section_id,
        "completed": body.completed,
        "completed_sections": done,
        "total_sections": total,
        "progress": _progress(done, total),
        "module_completed": total > 0 and done == total,
    }

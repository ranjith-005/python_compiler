"""Header search across the things a person can name (spec: titles only).

Deliberately not full-text over module content: that is a different problem
with different storage, and a search box that sometimes returns a paragraph
from the middle of a lesson is worse than one that reliably returns titles.

Every query is scoped by role. A student searches only what has been assigned
to them, so this endpoint can never become a way to enumerate drafts.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from .db import get_conn
from .deps import get_current_user
from .names import display_name

router = APIRouter(prefix="/api", tags=["search"])

PER_KIND = 5


def _like(term: str) -> str:
    """The search term as a LIKE pattern, with its wildcards defanged.

    `%` and `_` are LIKE's own operators, so a person typing "%" would
    otherwise match every row and turn the search box into a table dump. They
    are escaped here and every query below pairs this with ESCAPE '\\'.
    """
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/search")
def search(q: str = "", user: sqlite3.Row = Depends(get_current_user)) -> dict:
    term = q.strip()
    if not term:
        return {"results": []}
    like = _like(term)
    user_id = int(user["id"])
    is_trainer = user["role"] == "trainer"
    results: list[dict] = []

    with get_conn() as conn:
        if is_trainer:
            for row in conn.execute(
                "SELECT id, title FROM exercises WHERE trainer_id = ?"
                " AND title LIKE ? ESCAPE '\\'"
                " ORDER BY updated_at DESC LIMIT ?",
                (user_id, like, PER_KIND),
            ):
                results.append({
                    "kind": "exercise", "label": row["title"], "sub": "Exercise",
                    "link": f"/trainer/exercises/{row['id']}",
                })
            for row in conn.execute(
                "SELECT id, title FROM modules WHERE trainer_id = ?"
                " AND title LIKE ? ESCAPE '\\'"
                " ORDER BY updated_at DESC LIMIT ?",
                (user_id, like, PER_KIND),
            ):
                results.append({
                    "kind": "module", "label": row["title"], "sub": "Module",
                    "link": f"/trainer/modules/{row['id']}",
                })
            for row in conn.execute(
                "SELECT * FROM users WHERE role = 'student'"
                " AND (full_name LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\')"
                " LIMIT ?",
                (like, like, PER_KIND),
            ):
                results.append({
                    "kind": "student", "label": display_name(row),
                    "sub": row["email"],
                    "link": f"/trainer/students/{row['id']}",
                })
        else:
            # A student's half searches through the join that grants access, so
            # anything unassigned is not merely hidden -- it is unreachable.
            for row in conn.execute(
                "SELECT a.id, e.title FROM assignments a"
                " JOIN exercises e ON e.id = a.exercise_id"
                " WHERE a.student_id = ? AND e.title LIKE ? ESCAPE '\\' LIMIT ?",
                (user_id, like, PER_KIND),
            ):
                results.append({
                    "kind": "exercise", "label": row["title"], "sub": "Exercise",
                    "link": f"/student/assignments/{row['id']}/solve",
                })
            for row in conn.execute(
                "SELECT m.id, m.title FROM modules m"
                " JOIN module_assignments ma ON ma.module_id = m.id"
                " WHERE ma.student_id = ? AND m.status = 'published'"
                " AND m.title LIKE ? ESCAPE '\\' LIMIT ?",
                (user_id, like, PER_KIND),
            ):
                results.append({
                    "kind": "module", "label": row["title"], "sub": "Module",
                    "link": f"/student/modules/{row['id']}",
                })

    return {"results": results}

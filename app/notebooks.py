"""Notebook and cell CRUD, plus .ipynb import/export."""

from __future__ import annotations

import json
import sqlite3

import nbformat
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field

from .config import settings
from .db import create_notebook, get_conn, utcnow
from .deps import get_current_user

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])

CELL_TYPES = ("code", "markdown")


class NotebookIn(BaseModel):
    name: str = Field(default="Untitled.ipynb", min_length=1, max_length=160)


class NotebookRename(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class CellIn(BaseModel):
    cell_type: str = Field(default="code")
    source: str = Field(default="", max_length=1_000_000)
    position: int | None = None


class CellUpdate(BaseModel):
    source: str | None = Field(default=None, max_length=1_000_000)
    cell_type: str | None = None
    outputs: list | None = None
    execution_count: int | None = None


class ReorderIn(BaseModel):
    cell_ids: list[int]


# ----------------------------------------------------------------- helpers


def _own_notebook(conn: sqlite3.Connection, notebook_id: int, user_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM notebooks WHERE id = ? AND user_id = ?", (notebook_id, user_id)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Notebook not found.")
    return row


def _touch(conn: sqlite3.Connection, notebook_id: int) -> None:
    conn.execute("UPDATE notebooks SET updated_at = ? WHERE id = ?", (utcnow(), notebook_id))


def _cells(conn: sqlite3.Connection, notebook_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, position, cell_type, source, outputs, execution_count"
        " FROM cells WHERE notebook_id = ? ORDER BY position, id",
        (notebook_id,),
    ).fetchall()
    cells = []
    for row in rows:
        try:
            outputs = json.loads(row["outputs"])
        except (TypeError, ValueError):
            outputs = []
        cells.append(
            {
                "id": row["id"],
                "position": row["position"],
                "cell_type": row["cell_type"],
                "source": row["source"],
                "outputs": outputs,
                "execution_count": row["execution_count"],
            }
        )
    return cells


def _resequence(conn: sqlite3.Connection, notebook_id: int) -> None:
    rows = conn.execute(
        "SELECT id FROM cells WHERE notebook_id = ? ORDER BY position, id", (notebook_id,)
    ).fetchall()
    for index, row in enumerate(rows):
        conn.execute("UPDATE cells SET position = ? WHERE id = ?", (index, row["id"]))


# --------------------------------------------------------------- notebooks


@router.get("")
def list_notebooks(user: sqlite3.Row = Depends(get_current_user)) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT n.id, n.name, n.created_at, n.updated_at,"
            " (SELECT COUNT(*) FROM cells c WHERE c.notebook_id = n.id) AS cell_count"
            " FROM notebooks n WHERE n.user_id = ? ORDER BY n.updated_at DESC, n.id DESC",
            (user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def new_notebook(payload: NotebookIn, user: sqlite3.Row = Depends(get_current_user)) -> dict:
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM notebooks WHERE user_id = ?", (user["id"],)
        ).fetchone()["n"]
        if count >= settings.MAX_NOTEBOOKS_PER_USER:
            raise HTTPException(status_code=409, detail="Notebook limit reached.")
        notebook_id = create_notebook(conn, int(user["id"]), payload.name.strip())
        row = conn.execute("SELECT * FROM notebooks WHERE id = ?", (notebook_id,)).fetchone()
        return {**dict(row), "cells": _cells(conn, notebook_id)}


@router.get("/{notebook_id}")
def get_notebook(notebook_id: int, user: sqlite3.Row = Depends(get_current_user)) -> dict:
    with get_conn() as conn:
        row = _own_notebook(conn, notebook_id, int(user["id"]))
        return {**dict(row), "cells": _cells(conn, notebook_id)}


@router.put("/{notebook_id}")
def rename_notebook(
    notebook_id: int, payload: NotebookRename, user: sqlite3.Row = Depends(get_current_user)
) -> dict:
    with get_conn() as conn:
        _own_notebook(conn, notebook_id, int(user["id"]))
        conn.execute(
            "UPDATE notebooks SET name = ?, updated_at = ? WHERE id = ?",
            (payload.name.strip(), utcnow(), notebook_id),
        )
        row = conn.execute("SELECT * FROM notebooks WHERE id = ?", (notebook_id,)).fetchone()
    return dict(row)


@router.post("/{notebook_id}/duplicate", status_code=status.HTTP_201_CREATED)
def duplicate_notebook(notebook_id: int, user: sqlite3.Row = Depends(get_current_user)) -> dict:
    user_id = int(user["id"])
    with get_conn() as conn:
        row = _own_notebook(conn, notebook_id, user_id)
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM notebooks WHERE user_id = ?", (user_id,)
        ).fetchone()["n"]
        if count >= settings.MAX_NOTEBOOKS_PER_USER:
            raise HTTPException(status_code=409, detail="Notebook limit reached.")

        source = _cells(conn, notebook_id)
        copy_id = create_notebook(
            conn, user_id, f"Copy of {row['name']}", [(c["cell_type"], c["source"]) for c in source] or None
        )
        # Carry the outputs over too, so the copy looks like the original.
        new_cells = conn.execute(
            "SELECT id, position FROM cells WHERE notebook_id = ? ORDER BY position", (copy_id,)
        ).fetchall()
        for cell in new_cells:
            original = source[cell["position"]]
            conn.execute(
                "UPDATE cells SET outputs = ?, execution_count = ? WHERE id = ?",
                (json.dumps(original["outputs"]), original["execution_count"], cell["id"]),
            )
        created = conn.execute("SELECT * FROM notebooks WHERE id = ?", (copy_id,)).fetchone()
        return {**dict(created), "cells": _cells(conn, copy_id)}


@router.post("/{notebook_id}/clear-outputs")
def clear_outputs(notebook_id: int, user: sqlite3.Row = Depends(get_current_user)) -> dict:
    with get_conn() as conn:
        _own_notebook(conn, notebook_id, int(user["id"]))
        cur = conn.execute(
            "UPDATE cells SET outputs = '[]', execution_count = NULL, updated_at = ?"
            " WHERE notebook_id = ?",
            (utcnow(), notebook_id),
        )
        _touch(conn, notebook_id)
    return {"cleared": cur.rowcount}


@router.delete("/{notebook_id}")
def delete_notebook(notebook_id: int, user: sqlite3.Row = Depends(get_current_user)) -> dict:
    with get_conn() as conn:
        _own_notebook(conn, notebook_id, int(user["id"]))
        conn.execute("DELETE FROM cells WHERE notebook_id = ?", (notebook_id,))
        conn.execute("DELETE FROM notebooks WHERE id = ?", (notebook_id,))
    return {"ok": True}


# ------------------------------------------------------------------- cells


@router.post("/{notebook_id}/cells", status_code=status.HTTP_201_CREATED)
def add_cell(
    notebook_id: int, payload: CellIn, user: sqlite3.Row = Depends(get_current_user)
) -> dict:
    if payload.cell_type not in CELL_TYPES:
        raise HTTPException(status_code=422, detail="cell_type must be 'code' or 'markdown'.")
    with get_conn() as conn:
        _own_notebook(conn, notebook_id, int(user["id"]))
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM cells WHERE notebook_id = ?", (notebook_id,)
        ).fetchone()["n"]
        if total >= settings.MAX_CELLS_PER_NOTEBOOK:
            raise HTTPException(status_code=409, detail="Cell limit reached for this notebook.")
        position = total if payload.position is None else max(0, min(payload.position, total))
        conn.execute(
            "UPDATE cells SET position = position + 1 WHERE notebook_id = ? AND position >= ?",
            (notebook_id, position),
        )
        cur = conn.execute(
            "INSERT INTO cells (notebook_id, position, cell_type, source, outputs, updated_at)"
            " VALUES (?, ?, ?, ?, '[]', ?)",
            (notebook_id, position, payload.cell_type, payload.source, utcnow()),
        )
        _resequence(conn, notebook_id)
        _touch(conn, notebook_id)
        row = conn.execute(
            "SELECT id, position, cell_type, source, execution_count FROM cells WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return {**dict(row), "outputs": []}


@router.put("/{notebook_id}/cells/{cell_id}")
def update_cell(
    notebook_id: int,
    cell_id: int,
    payload: CellUpdate,
    user: sqlite3.Row = Depends(get_current_user),
) -> dict:
    with get_conn() as conn:
        _own_notebook(conn, notebook_id, int(user["id"]))
        row = conn.execute(
            "SELECT * FROM cells WHERE id = ? AND notebook_id = ?", (cell_id, notebook_id)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Cell not found.")
        source = row["source"] if payload.source is None else payload.source
        cell_type = row["cell_type"] if payload.cell_type is None else payload.cell_type
        if cell_type not in CELL_TYPES:
            raise HTTPException(status_code=422, detail="cell_type must be 'code' or 'markdown'.")
        outputs = row["outputs"] if payload.outputs is None else json.dumps(payload.outputs)
        if len(outputs) > settings.MAX_OUTPUT_BYTES_PER_CELL:
            outputs = json.dumps(
                [{"output_type": "stream", "name": "stderr", "text": "[output too large to store]"}]
            )
        execution_count = (
            row["execution_count"] if payload.execution_count is None else payload.execution_count
        )
        conn.execute(
            "UPDATE cells SET source = ?, cell_type = ?, outputs = ?, execution_count = ?,"
            " updated_at = ? WHERE id = ?",
            (source, cell_type, outputs, execution_count, utcnow(), cell_id),
        )
        _touch(conn, notebook_id)
        row = conn.execute("SELECT * FROM cells WHERE id = ?", (cell_id,)).fetchone()
    return {
        "id": row["id"],
        "position": row["position"],
        "cell_type": row["cell_type"],
        "source": row["source"],
        "outputs": json.loads(row["outputs"]),
        "execution_count": row["execution_count"],
    }


@router.delete("/{notebook_id}/cells/{cell_id}")
def delete_cell(
    notebook_id: int, cell_id: int, user: sqlite3.Row = Depends(get_current_user)
) -> dict:
    with get_conn() as conn:
        _own_notebook(conn, notebook_id, int(user["id"]))
        cur = conn.execute(
            "DELETE FROM cells WHERE id = ? AND notebook_id = ?", (cell_id, notebook_id)
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Cell not found.")
        _resequence(conn, notebook_id)
        _touch(conn, notebook_id)
    return {"ok": True}


@router.post("/{notebook_id}/reorder")
def reorder_cells(
    notebook_id: int, payload: ReorderIn, user: sqlite3.Row = Depends(get_current_user)
) -> dict:
    with get_conn() as conn:
        _own_notebook(conn, notebook_id, int(user["id"]))
        owned = {
            r["id"]
            for r in conn.execute(
                "SELECT id FROM cells WHERE notebook_id = ?", (notebook_id,)
            ).fetchall()
        }
        if set(payload.cell_ids) != owned:
            raise HTTPException(status_code=422, detail="cell_ids must list every cell exactly once.")
        for index, cell_id in enumerate(payload.cell_ids):
            conn.execute("UPDATE cells SET position = ? WHERE id = ?", (index, cell_id))
        _touch(conn, notebook_id)
    return {"ok": True}


# ---------------------------------------------------------- ipynb transfer


def _to_nbformat(name: str, cells: list[dict]) -> nbformat.NotebookNode:
    nb = nbformat.v4.new_notebook()
    nb.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
    nb.metadata["language_info"] = {"name": "python"}
    nb.metadata["pycompiler"] = {"name": name}
    for cell in cells:
        if cell["cell_type"] == "markdown":
            nb.cells.append(nbformat.v4.new_markdown_cell(cell["source"]))
            continue
        node = nbformat.v4.new_code_cell(cell["source"])
        node["execution_count"] = cell["execution_count"]
        node["outputs"] = [nbformat.from_dict(o) for o in cell["outputs"]]
        nb.cells.append(node)
    return nb


@router.get("/{notebook_id}/export")
def export_ipynb(notebook_id: int, user: sqlite3.Row = Depends(get_current_user)) -> Response:
    with get_conn() as conn:
        row = _own_notebook(conn, notebook_id, int(user["id"]))
        cells = _cells(conn, notebook_id)
    nb = _to_nbformat(row["name"], cells)
    filename = row["name"] if row["name"].endswith(".ipynb") else f"{row['name']}.ipynb"
    safe = "".join(ch for ch in filename if ch.isalnum() or ch in "._- ") or "notebook.ipynb"
    return Response(
        content=nbformat.writes(nb),
        media_type="application/x-ipynb+json",
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_ipynb(
    file: UploadFile = File(...), user: sqlite3.Row = Depends(get_current_user)
) -> dict:
    raw = await file.read()
    if len(raw) > 20_000_000:
        raise HTTPException(status_code=413, detail="Notebook file is too large.")
    try:
        nb = nbformat.reads(raw.decode("utf-8"), as_version=4)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Not a valid .ipynb file: {exc}")

    name = (file.filename or "Imported.ipynb").rsplit("/", 1)[-1]
    imported: list[tuple[str, str]] = []
    outputs_by_index: dict[int, list] = {}
    counts_by_index: dict[int, int | None] = {}
    for index, cell in enumerate(nb.cells[: settings.MAX_CELLS_PER_NOTEBOOK]):
        cell_type = "markdown" if cell.get("cell_type") == "markdown" else "code"
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        imported.append((cell_type, source))
        if cell_type == "code":
            outputs_by_index[index] = [dict(o) for o in cell.get("outputs", [])]
            counts_by_index[index] = cell.get("execution_count")

    if not imported:
        imported = [("code", "")]

    with get_conn() as conn:
        notebook_id = create_notebook(conn, int(user["id"]), name, imported)
        rows = conn.execute(
            "SELECT id, position FROM cells WHERE notebook_id = ? ORDER BY position", (notebook_id,)
        ).fetchall()
        for row in rows:
            index = row["position"]
            if index in outputs_by_index:
                conn.execute(
                    "UPDATE cells SET outputs = ?, execution_count = ? WHERE id = ?",
                    (json.dumps(outputs_by_index[index]), counts_by_index.get(index), row["id"]),
                )
        notebook = conn.execute(
            "SELECT * FROM notebooks WHERE id = ?", (notebook_id,)
        ).fetchone()
        return {**dict(notebook), "cells": _cells(conn, notebook_id)}

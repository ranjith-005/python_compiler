"""Workspace file manager: upload, browse, download, delete.

Files land in the same directory the user's kernel runs in, so an uploaded
`data.csv` is readable from a cell as `pd.read_csv("data.csv")`.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import settings
from .deps import get_current_user
from .workspace import (
    UnsafePath,
    relative_to_workspace,
    resolve_within,
    safe_name,
    workspace_dir,
    workspace_size,
)

router = APIRouter(prefix="/api/files", tags=["files"])
CHUNK = 1024 * 1024
# Files bigger than this open as "too large to edit" rather than loading into the browser.
MAX_EDIT_BYTES = 2_000_000
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


class MkdirIn(BaseModel):
    path: str = Field(default="")
    name: str = Field(min_length=1, max_length=180)


class RenameIn(BaseModel):
    path: str = Field(min_length=1)
    new_name: str = Field(min_length=1, max_length=180)


class SaveContentIn(BaseModel):
    path: str = Field(min_length=1)
    content: str = Field(default="", max_length=MAX_EDIT_BYTES)


def _safe(user_id: int, path: str | None) -> Path:
    try:
        return resolve_within(user_id, path)
    except UnsafePath as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _entry(user_id: int, item: Path) -> dict:
    try:
        stat = item.stat()
    except OSError:
        return {}
    return {
        "name": item.name,
        "path": relative_to_workspace(user_id, item),
        "is_dir": item.is_dir(),
        "size": 0 if item.is_dir() else stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
    }


@router.get("")
def list_files(
    path: str = Query(default=""), user: sqlite3.Row = Depends(get_current_user)
) -> dict:
    user_id = int(user["id"])
    target = _safe(user_id, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Folder not found.")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a folder.")

    entries = [e for e in (_entry(user_id, item) for item in target.iterdir()) if e]
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    relative = relative_to_workspace(user_id, target)
    return {
        "path": "" if relative == "." else relative,
        "entries": entries,
        "used_bytes": workspace_size(user_id),
        "quota_bytes": settings.MAX_WORKSPACE_BYTES,
    }


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_files(
    path: str = Query(default=""),
    files: list[UploadFile] = File(...),
    user: sqlite3.Row = Depends(get_current_user),
) -> dict:
    user_id = int(user["id"])
    target = _safe(user_id, path)
    target.mkdir(parents=True, exist_ok=True)
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Upload target is not a folder.")

    used = workspace_size(user_id)
    saved = []
    for upload in files:
        try:
            name = safe_name(upload.filename or "")
        except UnsafePath as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        destination = target / name
        written = 0
        try:
            with destination.open("wb") as out:
                while chunk := await upload.read(CHUNK):
                    written += len(chunk)
                    if written > settings.MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"{name} is larger than the {settings.MAX_UPLOAD_BYTES // 1_000_000} MB limit.",
                        )
                    if used + written > settings.MAX_WORKSPACE_BYTES:
                        raise HTTPException(status_code=413, detail="Workspace storage is full.")
                    out.write(chunk)
        except HTTPException:
            destination.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()
        used += written
        saved.append(_entry(user_id, destination))

    return {"saved": saved, "used_bytes": used, "quota_bytes": settings.MAX_WORKSPACE_BYTES}


@router.get("/download")
def download_file(
    path: str = Query(...), user: sqlite3.Row = Depends(get_current_user)
) -> FileResponse:
    target = _safe(int(user["id"]), path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        target, filename=target.name, media_type="application/octet-stream"
    )


@router.get("/raw")
def raw_file(path: str = Query(...), user: sqlite3.Row = Depends(get_current_user)) -> FileResponse:
    """Inline bytes, used to preview images in the file viewer."""
    target = _safe(int(user["id"]), path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    is_image = target.suffix.lower() in IMAGE_SUFFIXES
    media_type = f"image/{'jpeg' if target.suffix.lower() in {'.jpg', '.jpeg'} else target.suffix.lstrip('.').lower()}"
    return FileResponse(
        target,
        media_type=media_type if is_image else "application/octet-stream",
        headers={
            # Never render user-supplied HTML/SVG inline on our own origin.
            "Content-Disposition": ("inline" if is_image else f'attachment; filename="{target.name}"'),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@router.get("/content")
def read_content(path: str = Query(...), user: sqlite3.Row = Depends(get_current_user)) -> dict:
    """Open a file for viewing/editing in the browser."""
    target = _safe(int(user["id"]), path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    size = target.stat().st_size
    base = {"path": path, "name": target.name, "size": size}

    if target.suffix.lower() in IMAGE_SUFFIXES:
        return {**base, "kind": "image"}
    if size > MAX_EDIT_BYTES:
        return {**base, "kind": "large"}
    try:
        return {**base, "kind": "text", "content": target.read_text(encoding="utf-8")}
    except (UnicodeDecodeError, OSError):
        return {**base, "kind": "binary"}


@router.put("/content")
def save_content(payload: SaveContentIn, user: sqlite3.Row = Depends(get_current_user)) -> dict:
    user_id = int(user["id"])
    target = _safe(user_id, payload.path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    new_bytes = payload.content.encode("utf-8")
    projected = workspace_size(user_id) - target.stat().st_size + len(new_bytes)
    if projected > settings.MAX_WORKSPACE_BYTES:
        raise HTTPException(status_code=413, detail="Workspace storage is full.")
    target.write_bytes(new_bytes)
    return _entry(user_id, target)


@router.delete("")
def delete_path(
    path: str = Query(...), user: sqlite3.Row = Depends(get_current_user)
) -> dict:
    user_id = int(user["id"])
    target = _safe(user_id, path)
    if target == workspace_dir(user_id).resolve():
        raise HTTPException(status_code=400, detail="Cannot delete the workspace root.")
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    else:
        target.unlink(missing_ok=True)
    return {"ok": True}


@router.post("/mkdir", status_code=status.HTTP_201_CREATED)
def make_dir(payload: MkdirIn, user: sqlite3.Row = Depends(get_current_user)) -> dict:
    user_id = int(user["id"])
    parent = _safe(user_id, payload.path)
    try:
        name = safe_name(payload.name)
    except UnsafePath as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    target = parent / name
    if target.exists():
        raise HTTPException(status_code=409, detail="That folder already exists.")
    target.mkdir(parents=True)
    return _entry(user_id, target)


@router.post("/rename")
def rename_path(payload: RenameIn, user: sqlite3.Row = Depends(get_current_user)) -> dict:
    user_id = int(user["id"])
    target = _safe(user_id, payload.path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    try:
        name = safe_name(payload.new_name)
    except UnsafePath as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    destination = target.parent / name
    if destination.exists():
        raise HTTPException(status_code=409, detail="A file with that name already exists.")
    target.rename(destination)
    return _entry(user_id, destination)

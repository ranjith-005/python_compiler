"""Per-user workspace folder: the kernel's working directory and file store.

Every path that arrives from a request goes through `resolve_within`, which is
the only thing standing between a crafted path and the rest of the disk.
"""

from __future__ import annotations

import re
from pathlib import Path

from .config import settings

# Windows reserves these device names regardless of extension.
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class UnsafePath(ValueError):
    """The requested path escapes the workspace or is not a usable name."""


def workspace_dir(user_id: int) -> Path:
    path = settings.WORKSPACE_ROOT / f"user_{user_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_name(name: str) -> str:
    """Reduce an uploaded filename to a single safe path component."""
    name = (name or "").replace("\\", "/").split("/")[-1].strip()
    name = ILLEGAL_CHARS.sub("_", name).rstrip(". ")
    if not name or name in {".", ".."}:
        raise UnsafePath("Invalid file name.")
    stem = name.split(".")[0].upper()
    if stem in RESERVED_NAMES:
        name = f"_{name}"
    if len(name) > 180:
        head, _, ext = name.rpartition(".")
        name = f"{head[:150]}.{ext}" if ext else name[:180]
    return name


def resolve_within(user_id: int, relative: str | None) -> Path:
    """Resolve `relative` inside the user's workspace, or raise UnsafePath."""
    root = workspace_dir(user_id).resolve()
    candidate = (root / (relative or "")).resolve()
    if candidate != root and root not in candidate.parents:
        raise UnsafePath("Path is outside your workspace.")
    return candidate


def relative_to_workspace(user_id: int, path: Path) -> str:
    root = workspace_dir(user_id).resolve()
    return path.resolve().relative_to(root).as_posix()


def workspace_size(user_id: int) -> int:
    total = 0
    for item in workspace_dir(user_id).rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total

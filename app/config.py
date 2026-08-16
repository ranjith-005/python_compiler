"""Application settings, loaded from the environment with sane local defaults."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


def _load_env_file() -> None:
    """Minimal .env loader (KEY=VALUE per line). Existing env vars win."""
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _secret_key() -> str:
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    # Dev convenience: generate once and persist so sessions survive a restart.
    key = secrets.token_urlsafe(48)
    with ENV_FILE.open("a", encoding="utf-8") as fh:
        fh.write(f"SECRET_KEY={key}\n")
    os.environ["SECRET_KEY"] = key
    return key


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


_load_env_file()


class Settings:
    SECRET_KEY: str = _secret_key()
    DB_PATH: Path = Path(os.environ.get("DB_PATH", BASE_DIR / "pycompiler.db"))

    # Session cookie
    COOKIE_NAME: str = "session"
    COOKIE_SECURE: bool = os.environ.get("COOKIE_SECURE", "0") == "1"
    SESSION_DAYS: int = _int("SESSION_DAYS", 7)

    # Notebook runtime (one IPython kernel per user)
    KERNEL_STARTUP_SEC: int = _int("KERNEL_STARTUP_SEC", 60)
    CELL_TIMEOUT_SEC: int = _int("CELL_TIMEOUT_SEC", 120)
    KERNEL_IDLE_TIMEOUT_SEC: int = _int("KERNEL_IDLE_TIMEOUT_SEC", 1800)
    MAX_LIVE_KERNELS: int = _int("MAX_LIVE_KERNELS", 8)
    MAX_CELLS_PER_NOTEBOOK: int = _int("MAX_CELLS_PER_NOTEBOOK", 500)
    MAX_NOTEBOOKS_PER_USER: int = _int("MAX_NOTEBOOKS_PER_USER", 200)
    MAX_OUTPUT_BYTES_PER_CELL: int = _int("MAX_OUTPUT_BYTES_PER_CELL", 4_000_000)

    # Workspace files (uploads live in the kernel's working directory)
    WORKSPACE_ROOT: Path = Path(os.environ.get("WORKSPACE_ROOT", BASE_DIR / "workspaces"))
    MAX_UPLOAD_BYTES: int = _int("MAX_UPLOAD_BYTES", 200_000_000)
    MAX_WORKSPACE_BYTES: int = _int("MAX_WORKSPACE_BYTES", 1_000_000_000)


settings = Settings()

"""Application settings, loaded from the environment with sane local defaults."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
PROJECT_DIR = BASE_DIR.parent                       # repo root: backend/, frontend/, data/
ENV_FILE = Path(os.environ.get("ENV_FILE", PROJECT_DIR / ".env"))


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
    DB_PATH: Path = Path(os.environ.get("DB_PATH", PROJECT_DIR / "data" / "pycompiler.db"))

    # Templates and static assets
    FRONTEND_DIR: Path = Path(os.environ.get("FRONTEND_DIR", PROJECT_DIR / "frontend"))

    # Session cookie
    COOKIE_NAME: str = "session"
    COOKIE_SECURE: bool = os.environ.get("COOKIE_SECURE", "0") == "1"
    SESSION_DAYS: int = _int("SESSION_DAYS", 7)

    # A student's Run/Submit is cut off after min(this, 15) seconds
    CELL_TIMEOUT_SEC: int = _int("CELL_TIMEOUT_SEC", 120)

    # Per-student folder that each run uses as its working directory
    WORKSPACE_ROOT: Path = Path(
        os.environ.get("WORKSPACE_ROOT", PROJECT_DIR / "data" / "workspaces")
    )

    # Uploaded learning material (PDF/PPT/PPTX). The original file is kept and
    # stays associated with its module (module req 18). The cap is on bytes,
    # not on pages or slides -- a long deck is exactly what this must handle.
    MODULE_SOURCE_ROOT: Path = Path(
        os.environ.get("MODULE_SOURCE_ROOT", PROJECT_DIR / "data" / "module_sources")
    )
    MAX_MODULE_BYTES: int = _int("MAX_MODULE_BYTES", 80_000_000)

    # Groq structures the uploaded material into sections (module req 19).
    # The key lives only here and in app/groq_client.py -- it is never sent to
    # the browser, and no route returns it. With no key set the upload still
    # works: documents.build_sections() does the grouping offline instead.
    GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "").strip()
    GROQ_MODEL: str = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    GROQ_TIMEOUT_SEC: int = _int("GROQ_TIMEOUT_SEC", 90)
    GROQ_RETRIES: int = _int("GROQ_RETRIES", 3)
    GROQ_BACKOFF_SEC: float = float(os.environ.get("GROQ_BACKOFF_SEC", "2"))
    # Words per request. A chunk that is too big is refused by the model, and
    # one that is too small wastes calls and splits topics across requests.
    GROQ_CHUNK_WORDS: int = _int("GROQ_CHUNK_WORDS", 2500)


settings = Settings()

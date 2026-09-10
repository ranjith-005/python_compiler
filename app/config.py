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

    # Uploaded learning material (PDF/PPT/PPTX). The original file is kept and
    # stays associated with its module (module req 18). The cap is on bytes,
    # not on pages or slides -- a long deck is exactly what this must handle.
    MODULE_SOURCE_ROOT: Path = Path(
        os.environ.get("MODULE_SOURCE_ROOT", BASE_DIR / "module_sources")
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

    # Outbound mail, for the welcome a newly enrolled student receives. With no
    # host set nothing is sent and the trainer gets a mailto link instead, so
    # enrolment works out of the box on a machine with no mail server.
    SMTP_HOST: str = os.environ.get("SMTP_HOST", "").strip()
    SMTP_PORT: int = _int("SMTP_PORT", 587)
    SMTP_USER: str = os.environ.get("SMTP_USER", "").strip()
    SMTP_PASSWORD: str = os.environ.get("SMTP_PASSWORD", "")
    SMTP_STARTTLS: bool = os.environ.get("SMTP_STARTTLS", "1") == "1"
    SMTP_SSL: bool = os.environ.get("SMTP_SSL", "0") == "1"
    SMTP_TIMEOUT_SEC: int = _int("SMTP_TIMEOUT_SEC", 20)
    # The From address. Kept separate from SMTP_USER: relays often authenticate
    # as one identity and send as another.
    MAIL_FROM: str = os.environ.get("MAIL_FROM", "").strip()


settings = Settings()

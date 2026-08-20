"""FastAPI application: page routes + API wiring."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import assignments, auth, dashboards, files, notebooks, ws
from .config import settings
from .db import get_conn, init_db
from .auth import home_for
from .deps import get_optional_user
from .kernel import registry

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def asset_version() -> str:
    """Cache-buster for static URLs, so an edited .js/.css reaches the browser."""
    latest = 0.0
    for path in (APP_DIR / "static").rglob("*"):
        if path.is_file():
            try:
                latest = max(latest, path.stat().st_mtime)
            except OSError:
                continue
    return str(int(latest))


templates.env.globals["asset_v"] = asset_version


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    registry.start_reaper()
    try:
        yield
    finally:
        registry.stop_reaper()
        await registry.shutdown_all()


app = FastAPI(title="PyCompiler", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
app.include_router(auth.router)
app.include_router(dashboards.router)
app.include_router(assignments.router)
app.include_router(notebooks.router)
app.include_router(files.router)
app.include_router(ws.router)


@app.get("/", include_in_schema=False)
def index(user=Depends(get_optional_user)):
    return RedirectResponse(home_for(user["role"]) if user else "/login", status_code=302)


@app.get("/dashboard", include_in_schema=False)
def dashboard(user=Depends(get_optional_user)):
    """One address that lands each role on its own portal (SRS §1)."""
    return RedirectResponse(home_for(user["role"]) if user else "/login", status_code=302)


@app.get("/trainer", include_in_schema=False)
def trainer_page(request: Request, user=Depends(get_optional_user)):
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user["role"] != "trainer":
        return RedirectResponse("/student", status_code=302)
    return templates.TemplateResponse(
        request,
        "trainer_dashboard.html",
        {"email": user["email"], "name": user["full_name"] or user["email"]},
    )


@app.get("/student", include_in_schema=False)
def student_page(request: Request, user=Depends(get_optional_user)):
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user["role"] != "student":
        return RedirectResponse("/trainer", status_code=302)
    return templates.TemplateResponse(
        request,
        "student_dashboard.html",
        {"email": user["email"], "name": user["full_name"] or user["email"]},
    )


@app.get("/login", include_in_schema=False)
def login_page(request: Request, user=Depends(get_optional_user)):
    if user:
        return RedirectResponse(home_for(user["role"]), status_code=302)
    return templates.TemplateResponse(request, "login.html", {})


@app.get("/notebooks", include_in_schema=False)
def notebooks_page(request: Request, user=Depends(get_optional_user)):
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request, "notebooks.html", {"email": user["email"]})


@app.get("/nb/{notebook_id}", include_in_schema=False)
def notebook_page(notebook_id: int, request: Request, user=Depends(get_optional_user)):
    if not user:
        return RedirectResponse("/login", status_code=302)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, name FROM notebooks WHERE id = ? AND user_id = ?",
            (notebook_id, user["id"]),
        ).fetchone()
    if row is None:
        return RedirectResponse("/notebooks", status_code=302)
    return templates.TemplateResponse(
        request,
        "notebook.html",
        {
            "email": user["email"],
            "notebook_id": row["id"],
            "notebook_name": row["name"],
            "cell_timeout": settings.CELL_TIMEOUT_SEC,
        },
    )


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    return {"ok": True}

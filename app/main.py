"""FastAPI application: page routes + API wiring."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import assignments, auth, dashboards, files, modules, notebooks, ws
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
app.include_router(modules.router)
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


@app.get("/trainer/students", include_in_schema=False)
def trainer_students_page(request: Request, user=Depends(get_optional_user)):
    """Dedicated roster view, kept separate from the trainer overview."""
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user["role"] != "trainer":
        return RedirectResponse("/student", status_code=302)
    return templates.TemplateResponse(
        request,
        "trainer_students.html",
        {"name": user["full_name"] or user["email"]},
    )


@app.get("/profile", include_in_schema=False)
def profile_page(request: Request, user=Depends(get_optional_user)):
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request, "profile.html", {"user": user, "back": home_for(user["role"])}
    )


# Literal routes, not /trainer/{section}. A single-segment path parameter here
# matches every future /trainer/<page>, swallowing it before its own route is
# reached -- which is exactly what happened when the modules pages arrived.
@app.get("/trainer/exercises", include_in_schema=False)
def trainer_exercises_page(request: Request, user=Depends(get_optional_user)):
    return _trainer_page(request, user, "trainer_section.html", {"section": "exercises"})


@app.get("/trainer/queue", include_in_schema=False)
def trainer_queue_page(request: Request, user=Depends(get_optional_user)):
    return _trainer_page(request, user, "trainer_section.html", {"section": "queue"})


@app.get("/student/exercises", include_in_schema=False)
def student_exercises_page(request: Request, user=Depends(get_optional_user)):
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user["role"] != "student":
        return RedirectResponse("/trainer", status_code=302)
    return templates.TemplateResponse(request, "student_exercises.html", {"name": user["full_name"] or user["email"]})


@app.get("/activity", include_in_schema=False)
def activity_page(request: Request, user=Depends(get_optional_user)):
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request,
        "activity.html",
        {
            "back": home_for(user["role"]),
            "name": user["full_name"] or user["email"],
            "role": user["role"],
        },
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
    return templates.TemplateResponse(request, "notebooks.html", {"name": user["full_name"] or user["email"]})


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
            "name": user["full_name"] or user["email"],
            "notebook_id": row["id"],
            "notebook_name": row["name"],
            "cell_timeout": settings.CELL_TIMEOUT_SEC,
        },
    )


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    return {"ok": True}


# ══════════════ Phase B: detail pages (reqs 2, 6, 8, 13) ══════════════════
#
# Requirement 13 says a click opens a page, so the New exercise and Review
# sheets became routes rather than modals. Each renders a shell; the data
# arrives from /api.


def _trainer_page(request: Request, user, template: str, extra: dict | None = None):
    """Guard and render one of the trainer's detail pages."""
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user["role"] != "trainer":
        return RedirectResponse("/student", status_code=302)
    context = {"name": user["full_name"] or user["email"]}
    context.update(extra or {})
    return templates.TemplateResponse(request, template, context)


@app.get("/trainer/students/{student_id}", include_in_schema=False)
def trainer_student_detail_page(
    student_id: int, request: Request, user=Depends(get_optional_user)
):
    return _trainer_page(request, user, "student_detail.html", {"student_id": student_id})


@app.get("/trainer/students/{student_id}/profile", include_in_schema=False)
def trainer_student_profile_page(
    student_id: int, request: Request, user=Depends(get_optional_user)
):
    return _trainer_page(request, user, "student_personal.html", {"student_id": student_id})


@app.get("/trainer/students/{student_id}/exercises/{exercise_id}", include_in_schema=False)
def trainer_student_exercise_page(
    student_id: int, exercise_id: int, request: Request, user=Depends(get_optional_user)
):
    return _trainer_page(
        request,
        user,
        "student_exercise_detail.html",
        {"student_id": student_id, "exercise_id": exercise_id},
    )


# Declared before /trainer/exercises/{exercise_id} so the literal paths win.
@app.get("/trainer/exercises/new", include_in_schema=False)
def trainer_new_exercise_page(request: Request, user=Depends(get_optional_user)):
    return _trainer_page(request, user, "exercise_form.html")


@app.get("/trainer/exercises/drafts", include_in_schema=False)
def trainer_drafts_page(request: Request, user=Depends(get_optional_user)):
    return _trainer_page(request, user, "exercise_drafts.html")


@app.get("/trainer/exercises/{exercise_id}", include_in_schema=False)
def trainer_exercise_detail_page(
    exercise_id: int, request: Request, user=Depends(get_optional_user)
):
    return _trainer_page(request, user, "exercise_detail.html", {"exercise_id": exercise_id})


@app.get("/trainer/submissions/{submission_id}", include_in_schema=False)
def trainer_review_page(submission_id: int, request: Request, user=Depends(get_optional_user)):
    return _trainer_page(request, user, "review.html", {"submission_id": submission_id})


# ══════════════ Phase C: learning modules (reqs 14, 15, 17) ════════════════


@app.get("/trainer/modules", include_in_schema=False)
def trainer_modules_page(request: Request, user=Depends(get_optional_user)):
    return _trainer_page(request, user, "modules_trainer.html")


@app.get("/trainer/modules/{module_id}", include_in_schema=False)
def trainer_module_detail_page(
    module_id: int, request: Request, user=Depends(get_optional_user)
):
    return _trainer_page(request, user, "module_review.html", {"module_id": module_id})


def _student_page(request: Request, user, template: str, extra: dict | None = None):
    """Guard and render one of the student's pages."""
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user["role"] != "student":
        return RedirectResponse("/trainer", status_code=302)
    context = {"name": user["full_name"] or user["email"]}
    context.update(extra or {})
    return templates.TemplateResponse(request, template, context)


@app.get("/student/modules", include_in_schema=False)
def student_modules_page(request: Request, user=Depends(get_optional_user)):
    return _student_page(request, user, "modules_student.html")


@app.get("/student/modules/{module_id}", include_in_schema=False)
def student_module_player_page(
    module_id: int, request: Request, user=Depends(get_optional_user)
):
    return _student_page(request, user, "module_player.html", {"module_id": module_id})

# Portal Redesign — Phase 3 (Solve Page & Messages) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the notebook as the place a student answers an exercise with a conventional editor page — description on top, code left, input and output right, Run and Submit — and replace corner toasts with a centred status message.

**Architecture:** A student's solution currently lives in notebook cells and is stitched together at submit time. Phase 3 gives assignments their own `solution_code` column, backfills the existing notebooks into it once, and points Run, autosave and Submit at that column. The notebook survives for modules and free practice; only the exercise path leaves it. The evaluation machinery is unchanged — `_evaluate` already runs a solution as a subprocess against test cases, and the new Run endpoint reuses that same mechanism with the student's own stdin.

**Tech Stack:** FastAPI, Jinja2, SQLite (`sqlite3`, no ORM), Pydantic v2, vanilla JavaScript (no build step, no CDN), pytest + `fastapi.testclient`.

**Spec:** `docs/superpowers/specs/2026-09-02-portal-redesign-design.md`

## Global Constraints

- Run Python ONLY through `./.venv/Scripts/python.exe`. Never bare `python` or `python3` — `python3` is a broken Store stub on this machine.
- Tests: `./.venv/Scripts/python.exe -m pytest`, always FOREGROUND. Never `run_in_background`, never a trailing `&`. Four implementers have already lost 20+ minutes each to this.
- This environment never prints pytest's final "N passed" line. Judge by exit code; counts from `pytest --collect-only -q | tail -3`.
- No new runtime dependencies. **No CDN and no build step** — the editor is plain `<textarea>`, not CodeMirror or Monaco.
- Schema changes are additive and idempotent, via the migration helpers in `app/db.py`. Never `DROP COLUMN`, never rebuild a table.
- **Never build DOM with `innerHTML` from data.** Use `el()` from `dashboard_common.js`.
- `.stat` cards emit `class: "label"` / `"value"` / `"sub"` — never rename; `.stat` is shared by nine consumers.
- A display name is NEVER a raw email address.
- Page routes must be LITERAL and declared before any single-segment path parameter that could swallow them.
- Student-facing endpoints are guarded with `require_student`, and every assignment lookup goes through `_load_assignment`, which scopes by `student_id`.
- Commit after every task. Stay on branch `portal-redesign`. Do not merge, push, rebase, or force-anything.

---

### Task 1: The solution store and its backfill

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_phase3.py` (new)

**Interfaces:**
- Produces: `assignments.solution_code` and `assignments.last_stdin`, plus a one-time migration that stitches each existing assignment's notebook code into `solution_code` so no in-flight work is lost. Every later task reads and writes those columns.

`app/db.py` has `_migrate_user_columns` for the `users` table but nothing equivalent for the platform tables. Add one.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_phase3.py`:

```python
from conftest import register, register_trainer


def test_assignments_have_a_solution_store(client):
    from app.db import get_conn

    register(client)
    with get_conn() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(assignments)")}
    assert "solution_code" in columns
    assert "last_stdin" in columns


def test_the_backfill_runs_once_and_is_recorded(client):
    from app.db import get_conn, init_db

    register(client)
    init_db()  # a second start must not re-run the backfill
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM migrations WHERE key = 'notebook_code_to_solution_v1'"
        ).fetchone()[0]
    assert rows == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_phase3.py -v`
Expected: FAIL — the columns do not exist.

- [ ] **Step 3: Add the platform migration**

In `app/db.py`, alongside `_migrate_user_columns`:

```python
def _migrate_platform_columns(conn: sqlite3.Connection) -> None:
    """Additive columns for tables in PLATFORM_SCHEMA.

    Mirrors _migrate_user_columns; the platform tables had no equivalent because
    every earlier change could be expressed in CREATE TABLE IF NOT EXISTS.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(assignments)")}
    for column, ddl in (
        ("solution_code", "TEXT NOT NULL DEFAULT ''"),
        ("last_stdin", "TEXT NOT NULL DEFAULT ''"),
    ):
        if column not in existing:
            conn.execute(f"ALTER TABLE assignments ADD COLUMN {column} {ddl}")
```

- [ ] **Step 4: Add the one-time backfill**

Also in `app/db.py`:

```python
def _backfill_solution_code(conn: sqlite3.Connection) -> None:
    """Carry each assignment's notebook code into its own solution column.

    The exercise solve surface moves off notebooks in this phase. Without this,
    every student with work in progress would open the new editor and find it
    empty.
    """
    key = "notebook_code_to_solution_v1"
    if conn.execute("SELECT 1 FROM migrations WHERE key = ?", (key,)).fetchone():
        return
    rows = conn.execute(
        "SELECT id, notebook_id FROM assignments"
        " WHERE notebook_id IS NOT NULL AND solution_code = ''"
    ).fetchall()
    for row in rows:
        cells = conn.execute(
            "SELECT source FROM cells WHERE notebook_id = ? AND cell_type = 'code'"
            " ORDER BY position",
            (row["notebook_id"],),
        ).fetchall()
        code = "\n\n".join(c["source"] for c in cells if c["source"].strip())
        if code:
            conn.execute(
                "UPDATE assignments SET solution_code = ? WHERE id = ?", (code, row["id"])
            )
    conn.execute("INSERT INTO migrations (key, applied_at) VALUES (?, ?)", (key, utcnow()))
```

Call both from `init_db`, after `_migrate_user_columns`:

```python
        _migrate_platform_columns(conn)
        _backfill_solution_code(conn)
```

Order matters: the columns must exist before the backfill writes to them.

- [ ] **Step 5: Run the tests, then the suite**

`tests/test_phase3.py` → PASS (2). Full suite → exit 0.

- [ ] **Step 6: Commit**

```bash
git add app/db.py tests/test_phase3.py
git commit -m "Give assignments their own solution store and backfill it"
```

---

### Task 2: Run, autosave, and submitting from the new store

**Files:**
- Modify: `app/assignments.py`, `app/schemas.py`
- Test: `tests/test_phase3.py`

**Interfaces:**
- Produces: `POST /api/assignments/{id}/run` → `{stdout, stderr, timed_out, duration_ms}`; `PATCH /api/assignments/{id}/code` → `{"ok": true}`; and `submit_assignment` now evaluating `solution_code`. Task 4's page calls all three.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_phase3.py`:

```python
def _make_assignment(client):
    """A trainer creates and assigns one exercise; returns (assignment_id, student_client)."""
    register_trainer(client, email="t@example.com")
    students = client.get("/api/students").json()
    if not students:
        client.cookies.clear()
        register(client, email="learner@example.com")
        client.cookies.clear()
        register_trainer(client, email="t2@example.com")
        students = client.get("/api/students").json()
    client.post("/api/exercises", json={
        "title": "Echo", "problem_statement": "Read a line and print it.",
        "sample_input": "hi", "sample_output": "hi", "status": "published",
        "test_cases": [{"stdin": "hi\n", "expected_output": "hi", "is_hidden": False}],
        "assign_to": [students[0]["id"]],
    })
    client.cookies.clear()
    client.post("/auth/login", json={"email": "learner@example.com", "password": "password123"})
    assignment = client.get("/api/dashboard/student").json()["assignments"][0]
    return assignment["id"]


def test_run_executes_against_custom_stdin_without_recording_a_submission(client):
    assignment_id = _make_assignment(client)
    before = len(client.get("/api/dashboard/student").json()["assignments"])

    result = client.post(f"/api/assignments/{assignment_id}/run", json={
        "code": "print(input().upper())", "stdin": "hello\n",
    })
    assert result.status_code == 200
    body = result.json()
    assert body["stdout"].strip() == "HELLO"
    assert body["timed_out"] is False

    after = client.get("/api/dashboard/student").json()["assignments"][0]
    assert after["submission_id"] is None, "run must not create a submission"
    assert before == 1


def test_run_reports_an_error_without_raising(client):
    assignment_id = _make_assignment(client)
    body = client.post(f"/api/assignments/{assignment_id}/run", json={
        "code": "raise ValueError('boom')", "stdin": "",
    }).json()
    assert "boom" in body["stderr"]
    assert body["timed_out"] is False


def test_code_autosaves_and_survives_a_reload(client):
    assignment_id = _make_assignment(client)
    saved = client.patch(f"/api/assignments/{assignment_id}/code", json={
        "code": "x = 1", "stdin": "7\n",
    })
    assert saved.status_code == 200
    detail = client.get(f"/api/assignments/{assignment_id}").json()
    assert detail["solution_code"] == "x = 1"
    assert detail["last_stdin"] == "7\n"


def test_submit_evaluates_the_saved_solution_not_a_notebook(client):
    assignment_id = _make_assignment(client)
    client.patch(f"/api/assignments/{assignment_id}/code", json={
        "code": "print(input())", "stdin": "",
    })
    verdict = client.post(f"/api/assignments/{assignment_id}/submit").json()
    assert verdict["result"] == "accepted"
    assert verdict["passed"] == verdict["total"] == 1


def test_submitting_an_empty_solution_is_rejected_clearly(client):
    assignment_id = _make_assignment(client)
    response = client.post(f"/api/assignments/{assignment_id}/submit")
    assert response.status_code == 409
    assert "before submitting" in response.json()["detail"].lower()


def test_another_students_assignment_is_not_reachable(client):
    assignment_id = _make_assignment(client)
    client.cookies.clear()
    register(client, email="intruder@example.com")
    for call in (
        lambda: client.post(f"/api/assignments/{assignment_id}/run", json={"code": "1", "stdin": ""}),
        lambda: client.patch(f"/api/assignments/{assignment_id}/code", json={"code": "1", "stdin": ""}),
    ):
        assert call().status_code in (403, 404)
```

- [ ] **Step 2: Run to verify they fail**

Expected: 404s — the two new routes do not exist.

- [ ] **Step 3: Add the schemas**

In `app/schemas.py`:

```python
class SolutionIn(BaseModel):
    """The student's current editor contents, autosaved as they work."""

    code: str = Field(default="", max_length=200_000)
    stdin: str = Field(default="", max_length=100_000)
```

`RunIn` already exists for module practice snippets; this is a separate shape because the solve page also carries stdin.

- [ ] **Step 4: Add run and autosave**

In `app/assignments.py`, beside `open_assignment`:

```python
@router.post("/assignments/{assignment_id}/run")
def run_solution(
    assignment_id: int, body: SolutionIn, user: sqlite3.Row = Depends(require_student)
) -> dict:
    """Run the editor's code against the student's own input.

    Deliberately does NOT record a submission: this is the try-it button, and a
    student may press it as often as they like.
    """
    student_id = int(user["id"])
    with get_conn() as conn:
        _load_assignment(conn, assignment_id, student_id)
        conn.execute(
            "UPDATE assignments SET solution_code = ?, last_stdin = ? WHERE id = ?",
            (body.code, body.stdin, assignment_id),
        )

    started = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", body.code],
            input=body.stdin,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_SEC,
            cwd=str(workspace_dir(student_id)),
        )
        stdout, stderr, timed_out = proc.stdout, proc.stderr, False
    except subprocess.TimeoutExpired:
        stdout, stderr, timed_out = "", f"Timed out after {RUN_TIMEOUT_SEC}s.", True

    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    return {
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "duration_ms": duration_ms,
    }


@router.patch("/assignments/{assignment_id}/code")
def save_solution(
    assignment_id: int, body: SolutionIn, user: sqlite3.Row = Depends(require_student)
) -> dict:
    """Autosave the editor, so a refresh never loses work."""
    student_id = int(user["id"])
    now = utcnow()
    with get_conn() as conn:
        row = _load_assignment(conn, assignment_id, student_id)
        status_next = "in_progress" if row["status"] == "assigned" else row["status"]
        conn.execute(
            "UPDATE assignments SET solution_code = ?, last_stdin = ?,"
            " last_opened_at = ?, status = ? WHERE id = ?",
            (body.code, body.stdin, now, status_next, assignment_id),
        )
    return {"ok": True}
```

Add `SolutionIn` to the schema imports. `datetime` and `timezone` are already imported; `subprocess`, `sys`, `RUN_TIMEOUT_SEC` and `workspace_dir` are already in this module.

- [ ] **Step 5: Submit from the new store**

In `submit_assignment`, replace the notebook guard and the code read:

```python
        if row["status"] in ("approved", "completed"):
            raise HTTPException(status_code=409, detail="This exercise is already closed.")

        code = row["solution_code"] or ""
        if not code.strip():
            raise HTTPException(
                status_code=409, detail="Write some code before submitting."
            )
```

Delete the `if row["notebook_id"] is None:` guard and the `_notebook_code(...)` call. `_load_assignment` must select `solution_code`; check its SELECT and widen it if needed.

- [ ] **Step 6: Return the stored code from the detail endpoint**

`assignment_detail` must include `solution_code` and `last_stdin` so the page can restore them. Add both to its returned dict.

- [ ] **Step 7: Run the tests, then the suite**

`tests/test_phase3.py` → PASS (8). Full suite → exit 0. `tests/test_dashboards.py` and `tests/test_trainer_detail.py` exercise submission; if either seeded code through a notebook, update it to seed `solution_code` — that is the intended change, not a regression.

- [ ] **Step 8: Commit**

```bash
git commit -am "Run, autosave and submit from the assignment's own solution store"
```

---

### Task 3: Retire the notebook from the exercise path

**Files:**
- Modify: `app/assignments.py`, `app/main.py`
- Test: `tests/test_phase3.py`

**Interfaces:**
- Produces: `open_assignment` returns `{"assignment_id", "status"}` and creates no notebook. `_exercise_cells` is deleted. `_notebook_code` survives only for the backfill.

- [ ] **Step 1: Write the failing test**

```python
def test_opening_an_exercise_no_longer_creates_a_notebook(client):
    assignment_id = _make_assignment(client)
    before = len(client.get("/api/notebooks").json())
    client.post(f"/api/assignments/{assignment_id}/open")
    after = client.get("/api/notebooks").json()
    assert len(after) == before, "opening an exercise must not create a notebook"
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Simplify `open_assignment`**

Replace its body with a status touch only:

```python
@router.post("/assignments/{assignment_id}/open")
def open_assignment(assignment_id: int, user: sqlite3.Row = Depends(require_student)) -> dict:
    """Mark the exercise opened. The work now happens on the solve page.

    This used to create a notebook seeded with the question. Exercises left the
    notebook in Phase 3; notebooks remain for modules and free practice.
    """
    student_id = int(user["id"])
    now = utcnow()
    with get_conn() as conn:
        row = _load_assignment(conn, assignment_id, student_id)
        status_next = "in_progress" if row["status"] == "assigned" else row["status"]
        conn.execute(
            "UPDATE assignments SET last_opened_at = ?, status = ? WHERE id = ?",
            (now, status_next, assignment_id),
        )
    return {"assignment_id": assignment_id, "status": status_next}
```

- [ ] **Step 4: Delete `_exercise_cells`**

Remove the function. Confirm nothing else calls it:

Run: `grep -rn "_exercise_cells" app/`
Expected: no output.

Keep `_notebook_code` — `app/db.py`'s backfill has its own inline copy, but leaving the helper costs nothing and other code may reference it. If the grep shows it now has no callers either, say so in your report rather than deleting it; that is a judgement for the reviewer.

- [ ] **Step 5: Run the tests, then the suite**

Full suite → exit 0. Any test asserting that opening an assignment produces a notebook is now asserting retired behaviour — update it, and say which in your report.

- [ ] **Step 6: Commit**

```bash
git commit -am "Stop creating a notebook when an exercise is opened"
```

---

### Task 4: The solve page

**Files:**
- Create: `app/templates/solve.html`, `app/static/js/solve.js`, and a `solve` section in `app/static/css/dashboard.css`
- Modify: `app/main.py`
- Modify: `app/static/js/student_exercises.js`
- Test: `tests/test_phase3.py`

**Interfaces:**
- Consumes: run, autosave, submit and detail from Task 2.
- Produces: `/student/assignments/{id}/solve`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_solve_page_renders_and_is_guarded(client):
    assignment_id = _make_assignment(client)
    page = client.get(f"/student/assignments/{assignment_id}/solve")
    assert page.status_code == 200
    for piece in ("Run", "Submit", "Input", "Output"):
        assert piece in page.text, piece

    client.cookies.clear()
    register_trainer(client, email="nosy@example.com")
    redirected = client.get(f"/student/assignments/{assignment_id}/solve", follow_redirects=False)
    assert redirected.status_code == 302


def test_someone_elses_assignment_redirects_rather_than_erroring(client):
    assignment_id = _make_assignment(client)
    client.cookies.clear()
    register(client, email="other@example.com")
    response = client.get(
        f"/student/assignments/{assignment_id}/solve", follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/student/exercises"
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Add the route**

In `app/main.py`, with the other literal student routes:

```python
@app.get("/student/assignments/{assignment_id}/solve", include_in_schema=False)
def student_solve_page(
    assignment_id: int, request: Request, user=Depends(get_optional_user)
):
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user["role"] != "student":
        return RedirectResponse("/trainer", status_code=302)
    with get_conn() as conn:
        owned = conn.execute(
            "SELECT 1 FROM assignments WHERE id = ? AND student_id = ?",
            (assignment_id, user["id"]),
        ).fetchone()
    if owned is None:
        return RedirectResponse("/student/exercises", status_code=302)
    return templates.TemplateResponse(
        request,
        "solve.html",
        {"name": display_name(user), "assignment_id": assignment_id},
    )
```

- [ ] **Step 4: Write the template**

Create `app/templates/solve.html`:

```jinja
{% extends "base.html" %}
{% from "_topbar.html" import topbar %}
{% block title %}Solve · Python Learning Platform{% endblock %}
{% block body_class %}colab dash{% endblock %}
{% block head %}
<link rel="stylesheet" href="/static/css/colab.css?v={{ asset_v() }}">
<link rel="stylesheet" href="/static/css/dashboard.css?v={{ asset_v() }}">
{% endblock %}

{% block content %}
{{ topbar('student', name, back='/student/exercises', heading='Exercise', current='exercises') }}

<main class="dash-main solve">
  <div class="dash-head">
    <div>
      <h1 id="ex-title">Loading…</h1>
      <p id="ex-meta"></p>
    </div>
    <span class="pill" id="ex-status"></span>
  </div>

  <section class="panel" id="problem-panel">
    <header><h2>Problem</h2></header>
    <div class="panel-body pad" id="problem-body"></div>
  </section>

  <div class="solve-grid">
    <section class="panel">
      <header><h2>Your solution</h2><span class="spacer"></span>
        <span class="cb-hint" id="save-state">Saved</span></header>
      <div class="panel-body pad">
        <textarea id="code" class="code-area" spellcheck="false"
                  aria-label="Your solution"></textarea>
      </div>
    </section>

    <div class="solve-side">
      <section class="panel">
        <header><h2>Input</h2></header>
        <div class="panel-body pad">
          <textarea id="stdin" class="code-area small" spellcheck="false"
                    aria-label="Input given to your program"></textarea>
        </div>
      </section>
      <section class="panel">
        <header><h2>Output</h2><span class="spacer"></span>
          <span class="cb-hint" id="run-time"></span></header>
        <div class="panel-body pad"><pre class="output" id="output"></pre></div>
      </section>
    </div>
  </div>

  <div class="row-actions page-actions">
    <button class="cb-btn" id="run-btn">Run</button>
    <button class="cb-btn primary" id="submit-btn">Submit</button>
  </div>
</main>

<div class="flash" id="flash" hidden></div>
<div class="toast" id="toast" hidden></div>
{% endblock %}

{% block scripts %}
<script>window.ASSIGNMENT_ID = {{ assignment_id }};</script>
<script src="/static/js/dashboard_common.js?v={{ asset_v() }}"></script>
<script src="/static/js/solve.js?v={{ asset_v() }}"></script>
{% endblock %}
```

- [ ] **Step 5: Write the page script**

Create `app/static/js/solve.js`. Build every node with `el()`; the problem statement is trainer-authored text.

```javascript
// The exercise solve page: description on top, editor left, input and output
// right. Replaces the notebook for graded work.
(function () {
  const D = window.Dash;
  const { el } = D;
  const id = window.ASSIGNMENT_ID;

  const code = document.getElementById("code");
  const stdin = document.getElementById("stdin");
  const output = document.getElementById("output");
  const saveState = document.getElementById("save-state");
  let saveTimer = null;
  let dirty = false;

  function field(label, value) {
    if (!value) return null;
    return el("div", { class: "field-block" },
      el("span", { class: "label", text: label }),
      el("pre", { class: "sample", text: value })
    );
  }

  async function load() {
    const a = await D.api(`/api/assignments/${id}`);
    document.getElementById("ex-title").textContent = a.title;
    document.getElementById("ex-meta").textContent =
      a.due_date ? `Due ${D.due(a.due_date)}` : "No due date";
    document.getElementById("ex-status").textContent = (a.status || "").replace(/_/g, " ");

    const body = document.getElementById("problem-body");
    body.textContent = "";
    body.append(el("p", { class: "statement", text: a.problem_statement || "" }));
    [field("Sample input", a.sample_input), field("Sample output", a.sample_output),
     field("Explanation", a.explanation)].forEach((n) => n && body.append(n));

    code.value = a.solution_code || a.starter_code || "";
    stdin.value = a.last_stdin || a.sample_input || "";
    dirty = false;
    saveState.textContent = "Saved";
  }

  async function save() {
    if (!dirty) return;
    try {
      await D.api(`/api/assignments/${id}/code`, {
        method: "PATCH",
        body: JSON.stringify({ code: code.value, stdin: stdin.value }),
      });
      dirty = false;
      saveState.textContent = "Saved";
    } catch (err) {
      saveState.textContent = "Not saved";
    }
  }

  function markDirty() {
    dirty = true;
    saveState.textContent = "Saving…";
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 900);
  }

  code.addEventListener("input", markDirty);
  stdin.addEventListener("input", markDirty);
  // A refresh or a closed tab must not lose work.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") save();
  });

  // Tab indents rather than leaving the editor.
  code.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    e.preventDefault();
    const start = code.selectionStart;
    code.setRangeText("    ", start, code.selectionEnd, "end");
    markDirty();
  });

  document.getElementById("run-btn").addEventListener("click", async () => {
    output.textContent = "Running…";
    try {
      const r = await D.api(`/api/assignments/${id}/run`, {
        method: "POST",
        body: JSON.stringify({ code: code.value, stdin: stdin.value }),
      });
      output.textContent = (r.stdout || "") + (r.stderr ? `\n${r.stderr}` : "");
      output.classList.toggle("err", Boolean(r.stderr) || r.timed_out);
      document.getElementById("run-time").textContent = `${r.duration_ms} ms`;
      dirty = false;
      saveState.textContent = "Saved";
    } catch (err) {
      output.textContent = err.message;
      output.classList.add("err");
    }
  });

  document.getElementById("submit-btn").addEventListener("click", async () => {
    await save();
    try {
      const v = await D.api(`/api/assignments/${id}/submit`, { method: "POST" });
      D.flash(
        v.result === "accepted"
          ? `Submitted — ${v.passed}/${v.total} tests passed`
          : `Submitted — ${v.passed}/${v.total} tests passed (${v.result.replace(/_/g, " ")})`,
        v.result === "accepted" ? "success" : "info"
      );
      load();
    } catch (err) {
      D.flash(err.message, "error");
    }
  });

  load().catch((err) => D.flash(err.message || "Unable to load this exercise.", "error"));
})();
```

`D.flash` arrives in Task 5. Until then this page will throw on submit — that is expected mid-phase, and Task 5 closes it. Note it in your report rather than inventing a stand-in.

- [ ] **Step 6: Style it**

Append a `solve` block to `app/static/css/dashboard.css`:

```css
/* ── exercise solve page ──────────────────────────────────────────── */

.solve-grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 16px; align-items: start; }
.solve-side { display: grid; gap: 16px; }
.code-area {
  width: 100%;
  min-height: 340px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--cell-bg);
  color: var(--text);
  font-family: var(--mono);
  font-size: 13px;
  line-height: 1.55;
  resize: vertical;
  tab-size: 4;
}
.code-area.small { min-height: 110px; }
.code-area:focus { outline: none; border-color: var(--blue); }
.output {
  margin: 0;
  min-height: 110px;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  font-family: var(--mono);
  font-size: 13px;
  color: var(--text);
}
.output.err { color: var(--red); }
.field-block { margin-top: 14px; }
.field-block .label { display: block; margin-bottom: 4px; }
.sample {
  margin: 0; padding: 8px 10px;
  background: var(--cell-bg); border: 1px solid var(--border);
  border-radius: 6px; font-family: var(--mono); font-size: 13px;
  white-space: pre-wrap;
}
.statement { margin: 0; white-space: pre-wrap; }

@media (max-width: 980px) { .solve-grid { grid-template-columns: 1fr; } }
```

- [ ] **Step 7: Point the exercises page at it**

In `app/static/js/student_exercises.js`, `openAssignment` currently POSTs `/open` and navigates to `/nb/${notebook_id}`. Change it to POST `/open` and then navigate to `/student/assignments/${a.id}/solve`.

- [ ] **Step 8: Run the tests, then the suite**

- [ ] **Step 9: Commit**

```bash
git commit -am "Add the exercise solve page"
```

---

### Task 5: Centred status messages

**Files:**
- Modify: `app/static/js/dashboard_common.js`, `app/static/css/dashboard.css`
- Modify: every page script that calls `D.toast`
- Test: `tests/test_phase3.py`

**Interfaces:**
- Produces: `D.flash(message, kind)` where kind is `success`, `error` or `info`. `D.toast` remains as a thin alias so nothing breaks mid-conversion, but no call site should use it when you are done.

The user's requirement: a confirmation should appear in the centre after an action completes, and must not be a pop-up dialog.

- [ ] **Step 1: Write the failing test**

```python
def test_pages_render_a_flash_region_and_no_page_calls_toast(client):
    register(client)
    assert 'id="flash"' in client.get("/student").text

    from pathlib import Path

    offenders = []
    for path in Path("app/static/js").glob("*.js"):
        if path.name in ("dashboard_common.js", "notebook.js"):
            continue  # the definer, and the notebook keeps its own local toast
        if "D.toast(" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert offenders == [], f"still calling D.toast: {offenders}"
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Add `flash`**

In `app/static/js/dashboard_common.js`, beside `toast`:

```javascript
  const flashEl = document.getElementById("flash");
  let flashTimer = null;

  // Requirement: confirmation appears in the centre after an action, and is not
  // a pop-up. Non-modal, does not trap focus, does not block interaction.
  function flash(message, kind) {
    if (!flashEl) return toast(message, kind === "error");
    flashEl.textContent = message;
    flashEl.className = `flash ${kind || "success"}`;
    flashEl.setAttribute("role", kind === "error" ? "alert" : "status");
    flashEl.hidden = false;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => (flashEl.hidden = true), 3200);
  }
```

Add `flash` to the returned object. Make it dismissable:

```javascript
  if (flashEl) flashEl.addEventListener("click", () => (flashEl.hidden = true));
```

- [ ] **Step 4: Style it**

```css
/* ── centred status message ───────────────────────────────────────── */

.flash {
  position: fixed;
  top: 84px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 60;
  max-width: min(560px, calc(100vw - 32px));
  padding: 12px 18px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  box-shadow: var(--shadow-card-hover);
  font-size: 14px;
  font-weight: 500;
  text-align: center;
  cursor: pointer;
}
.flash.success { border-color: var(--green); }
.flash.error   { border-color: var(--red); }
.flash.info    { border-color: var(--blue); }
```

It is fixed and centred horizontally, sits below the top bar, and is not modal — no backdrop, no focus trap.

- [ ] **Step 5: Add the region to every page that can flash**

Add `<div class="flash" id="flash" hidden></div>` beside the existing `<div class="toast" ...>` in: `trainer_dashboard.html`, `student_dashboard.html`, `student_exercises.html`, `trainer_section.html`, `trainer_students.html`, `settings.html`, `exercise_form.html`, `exercise_detail.html`, `exercise_drafts.html`, `student_detail.html`, `review.html`, `modules_trainer.html`, `modules_student.html`, `module_player.html`, `module_review.html`, `activity.html`, `student_personal.html`, `student_exercise_detail.html`, and `solve.html` (already added in Task 4).

Verify none was missed:

Run: `grep -L 'id="flash"' app/templates/*.html`
Expected: only `base.html`, `_topbar.html`, `login.html`, `profile.html`, `notebook.html`, `notebooks.html` — pages with no toast today.

- [ ] **Step 6: Convert the call sites**

Replace `D.toast(msg)` with `D.flash(msg, "success")` and `D.toast(msg, true)` with `D.flash(msg, "error")` across `student_dashboard.js`, `student_exercises.js`, `trainer_dashboard.js`, `trainer_detail.js`, `trainer_students.js`, `trainer_section.js`, `modules.js`, `settings.js` and `solve.js`.

Leave `notebook.js` alone — it defines its own local `toast` and is not part of this conversion.

Give each message the wording the spec lists where one applies: *Exercise created*, *Assigned*, *Draft saved*, *Submitted*, *Reviewed*, *Query sent*, *Reply sent*, *Password changed*, *Profile saved*, *Theme saved*.

- [ ] **Step 7: Run the tests, then the suite**

- [ ] **Step 8: Commit**

```bash
git commit -am "Replace corner toasts with a centred status message"
```

---

## Phase 3 exit criteria

- A student opens an exercise and lands on `/student/assignments/{id}/solve`, not a notebook.
- The page shows the description, an editor, an input box and an output pane, with Run and Submit.
- Run executes against the student's own input and records no submission.
- Code autosaves and survives a refresh.
- Submit evaluates the saved solution against the test cases.
- Opening an exercise creates no notebook; `/nb/` still serves modules and free practice.
- Existing in-flight work was carried into `solution_code` by the one-time backfill.
- Confirmations appear centred, not in a corner and not as a dialog.
- No page script calls `D.toast`.
- `./.venv/Scripts/python.exe -m pytest -q` is green.

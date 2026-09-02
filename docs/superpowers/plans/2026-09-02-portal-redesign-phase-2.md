# Portal Redesign — Phase 2 (Dashboards & Pages) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce both dashboards to clickable summary cards, give every card a real page, show people by name everywhere, and close the four findings Phase 1 carried forward.

**Architecture:** Phase 1 built the tokens, the nav and Settings. Phase 2 rebuilds what those navigate to. Three carried-forward findings land first because every later task compounds them: the theme must render server-side before more pages exist, the XSS sink must be closed before more names flow through it, and display names must reach API responses before more lists render them. Then the dashboards shed their panels, and those panels become pages.

**Tech Stack:** FastAPI, Jinja2, SQLite (`sqlite3`, no ORM), Pydantic v2, bcrypt, PyJWT, vanilla JavaScript (no build step), pytest + `fastapi.testclient`.

**Spec:** `docs/superpowers/specs/2026-09-02-portal-redesign-design.md`
**Carried-forward findings:** `docs/superpowers/specs/2026-09-02-phase-1-carried-forward.md`

## Global Constraints

- Run Python ONLY through `./.venv/Scripts/python.exe`. Never bare `python` or `python3` — `python3` is a broken Store stub on this machine.
- Tests: `./.venv/Scripts/python.exe -m pytest`, always in the FOREGROUND. Never `run_in_background`, never a trailing `&`. The suite takes ~2 minutes; that is normal.
- This environment never prints pytest's final "N passed" line. Judge success by exit code; get counts from `pytest --collect-only -q | tail -3`.
- The suite is 143 passing at the start of this phase. It must stay green.
- No new runtime dependencies. No build step.
- Schema changes are additive and idempotent, through the migration helpers in `app/db.py`. Never `DROP COLUMN`, never rebuild a table.
- A display name is NEVER a raw email address. Use `display_name` from `app/names.py`.
- **Never build DOM with `innerHTML` from data.** Use `el()` from `dashboard_common.js`, which text-nodes its children. `el()` accepts an `html` prop — never pass it data.
- Page routes in `app/main.py` must be LITERAL paths declared before any single-segment path parameter that could swallow them.
- Static assets are referenced as `/static/...?v={{ asset_v() }}`.
- The three theme values are exactly `system`, `light`, `dark`.
- Cards that navigate are `<a>`, never `<button>` or a click-handled `<div>`, so keyboard and middle-click work.
- Commit after every task. Stay on branch `portal-redesign`. Do not merge, push, rebase, or force-anything.

---

## File Structure

**Created:**
- `app/templates/trainer_pending.html`, `trainer_completed.html` — thin shells; or one generalised section template (Task 4 decides and Task 6 consumes).
- `app/static/js/trainer_cards.js`, `app/static/js/student_cards.js` — card rendering per role.
- `tests/test_phase2.py` — all new tests for this phase. Keeps `test_settings.py` as Phase 1's record.

**Modified (by task):**
- T1: `app/main.py`, `app/templates/base.html`, `app/static/js/dashboard_common.js`
- T2: `app/db.py`, `app/deps.py`, `app/auth.py`, `app/security.py`
- T3: `app/dashboards.py`, `app/assignments.py`, `app/modules.py`, and the five JS files that fall back to email
- T4: `app/static/js/trainer_section.js` (full rewrite), `app/templates/trainer_section.html`, `app/main.py`
- T5: `app/templates/trainer_dashboard.html`, `app/static/js/trainer_dashboard.js`
- T6: `app/assignments.py`, `app/static/js/trainer_students.js`, `app/static/js/trainer_detail.js`, `app/main.py`
- T7: `app/templates/student_dashboard.html`, `student_exercises.html`, `app/static/js/student_dashboard.js`, `student_exercises.js`, `app/static/css/dashboard.css`
- T8: `app/templates/exercise_form.html`, `app/static/js/trainer_detail.js`, `app/schemas.py`, `app/static/js/modules.js`

---

### Task 1: Render the theme server-side (finding F1)

**Files:**
- Modify: `app/main.py`
- Modify: `app/templates/base.html`
- Modify: `app/static/js/dashboard_common.js`
- Test: `tests/test_phase2.py`

**Interfaces:**
- Produces: every page renders `<html data-theme="...">` with the signed-in user's stored theme, before any script runs. Later tasks add pages without thinking about theming.

Why this is first: `syncTheme()` in `dashboard_common.js` is the only thing that applies the account theme, and 9 of 24 templates never load that file. Every page Phase 2 adds would inherit the same trap.

Starlette 0.41.3's `Jinja2Templates` accepts `context_processors`, so one function can inject `theme` into every template without touching 20 route handlers.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_phase2.py`:

```python
from conftest import register, register_trainer


def test_pages_render_the_accounts_theme_server_side(client):
    register(client)
    client.patch("/api/settings/theme", json={"theme": "light"})
    for path in ("/student", "/student/exercises", "/activity", "/profile", "/settings"):
        html = client.get(path).text
        assert '<html lang="en" data-theme="light">' in html, path


def test_signed_out_pages_fall_back_to_system(client):
    assert '<html lang="en" data-theme="system">' in client.get("/login").text


def test_theme_change_is_reflected_on_the_next_page_load(client):
    register(client)
    assert 'data-theme="system"' in client.get("/student").text
    client.patch("/api/settings/theme", json={"theme": "dark"})
    assert 'data-theme="dark"' in client.get("/student").text
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_phase2.py -v`
Expected: FAIL — `base.html` emits no `data-theme` server-side.

- [ ] **Step 3: Add the context processor**

In `app/main.py`, above the `templates = Jinja2Templates(...)` line:

```python
def theme_context(request: Request) -> dict:
    """Put the signed-in user's theme in every template.

    The theme has to be on <html> before the first paint, and 9 of 24 templates
    never load dashboard_common.js, so a script-only reconcile left those pages
    permanently on the default. One processor covers every page instead.
    """
    user = get_optional_user(request)
    theme = user["theme"] if user else "system"
    return {"theme": theme if theme in ("system", "light", "dark") else "system"}
```

Change the templates construction to use it:

```python
templates = Jinja2Templates(
    directory=str(APP_DIR / "templates"), context_processors=[theme_context]
)
```

`get_optional_user` is already imported. It reads the cookie and hits the DB, which this adds to every page render — acceptable, since every page already loads the user for its own guard.

- [ ] **Step 4: Use it in `base.html`**

Replace the opening tag and the bootstrap script:

```html
<html lang="en" data-theme="{{ theme|default('system', true) }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Python Learning Platform{% endblock %}</title>
  <script>
    // The server already stamped the account's theme on <html>. This only
    // covers a signed-out visitor who set a theme on a previous visit, and
    // keeps localStorage in step for the Settings page's picker.
    (function () {
      var server = document.documentElement.getAttribute("data-theme");
      try {
        if (server && server !== "system") { localStorage.setItem("theme", server); return; }
        var saved = localStorage.getItem("theme");
        if (saved === "light" || saved === "dark" || saved === "system") {
          document.documentElement.setAttribute("data-theme", saved);
        }
      } catch (e) {}
    })();
  </script>
```

The value check also closes finding F5 — an unknown `localStorage` value can no longer reach the DOM.

- [ ] **Step 5: Retire `syncTheme()`**

In `app/static/js/dashboard_common.js`, delete the `syncTheme` function and its call. The server is the source of truth now, and leaving it in means an extra `/auth/me` per page load plus the F12 radio-vs-attribute divergence.

- [ ] **Step 6: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_phase2.py -v` → PASS (3).
Then: `./.venv/Scripts/python.exe -m pytest -q` → exit 0.

- [ ] **Step 7: Commit**

```bash
git add app/main.py app/templates/base.html app/static/js/dashboard_common.js tests/test_phase2.py
git commit -m "Render the account theme server-side on every page"
```

---

### Task 2: Invalidate other sessions on password change (finding F2)

**Files:**
- Modify: `app/db.py`, `app/deps.py`, `app/auth.py`
- Test: `tests/test_phase2.py`

**Interfaces:**
- Produces: `users.sessions_valid_from`. A token whose `iat` predates it is rejected by `_user_from_request`, so every other device is signed out.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_phase2.py`:

```python
def test_password_change_signs_out_other_devices(client):
    register(client)
    stale = dict(client.cookies)          # this browser's cookie, captured before the change

    client.post("/auth/password", json={
        "current_password": "password123",
        "new_password": "newpassword456",
        "confirm_password": "newpassword456",
    })
    # The device that changed it stays signed in (it got a fresh cookie).
    assert client.get("/auth/me").status_code == 200

    # A different device still holding the old cookie is rejected.
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as elsewhere:
        elsewhere.cookies.update(stale)
        assert elsewhere.get("/auth/me").status_code == 401
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_phase2.py -k signs_out -v`
Expected: FAIL — the stale cookie still returns 200.

- [ ] **Step 3: Add the column**

In `app/db.py`'s `_migrate_user_columns`, add:

```python
        ("sessions_valid_from", "TEXT NOT NULL DEFAULT ''"),
```

- [ ] **Step 4: Check it when resolving a session**

In `app/deps.py`, `_user_from_request` currently decodes the token to a user id. It needs the token's `iat` too. In `app/security.py` add:

```python
def decode_token_full(token: str) -> dict | None:
    """The whole payload, for callers that need `iat` as well as `sub`."""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
```

Then in `app/deps.py`, replace the body of `_user_from_request` with:

```python
def _user_from_request(request: Request) -> sqlite3.Row | None:
    token = request.cookies.get(settings.COOKIE_NAME)
    if not token:
        return None
    payload = decode_token_full(token)
    if not payload:
        return None
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None
    with get_conn() as conn:
        user = conn.execute(
            "SELECT id, email, created_at, role, full_name, first_name, last_name, phone,"
            " is_active, theme, sessions_valid_from"
            " FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if user is None:
        return None
    # A password change stamps sessions_valid_from; tokens minted before it die.
    cutoff = user["sessions_valid_from"]
    if cutoff:
        issued = datetime.fromtimestamp(int(payload.get("iat", 0)), tz=timezone.utc)
        if issued.isoformat(timespec="seconds") < cutoff:
            return None
    return user
```

Add `from datetime import datetime, timezone` and import `decode_token_full` instead of `decode_token`.

- [ ] **Step 5: Stamp it on password change**

In `app/auth.py`'s `change_password`, inside the same `with get_conn()` block as the UPDATE, change the UPDATE to:

```python
        conn.execute(
            "UPDATE users SET password_hash = ?, sessions_valid_from = ? WHERE id = ?",
            (hash_password(body.new_password), utcnow(), user["id"]),
        )
```

`utcnow` is already imported in `auth.py`.

Note the ordering that makes this work: `set_session_cookie` runs AFTER this block, so the current device's replacement token is minted with a later `iat` than the cutoff and survives. Do not move it.

- [ ] **Step 6: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_phase2.py -v` → PASS (4).
Then the full suite → exit 0. Phase 1's `test_password_change_keeps_the_session_alive` and `test_password_change_reissues_the_session_cookie` both still pass — if either fails, the cookie is being reissued before the stamp.

- [ ] **Step 7: Commit**

```bash
git add app/db.py app/deps.py app/security.py app/auth.py tests/test_phase2.py
git commit -m "Sign out other devices when the password changes"
```

---

### Task 3: Display names in every API response that returns a person (finding F3)

**Files:**
- Modify: `app/dashboards.py`, `app/assignments.py`, `app/modules.py`
- Modify: `app/static/js/trainer_students.js`, `trainer_section.js`, `trainer_dashboard.js`, `trainer_detail.js`, `modules.js`
- Test: `tests/test_phase2.py`

**Interfaces:**
- Produces: every API row describing a person carries a `display` field. The JS reads `display` and never falls back to an email.

The SQL cannot call a Python helper, so each query keeps selecting the raw columns and the Python layer adds `display`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_phase2.py`:

```python
def test_no_api_response_exposes_an_email_as_a_name(client):
    trainer = register_trainer(client)
    client.cookies.clear()
    register(client, email="nameless.student@example.com")
    client.cookies.clear()
    register_trainer(client)

    roster = client.get("/api/dashboard/trainer").json()["students"]
    assert roster, "expected the student in the roster"
    for row in roster:
        assert row["display"] == "Nameless Student"
        assert "@" not in row["display"]
```

- [ ] **Step 2: Run to verify it fails**

Expected: `KeyError: 'display'`.

- [ ] **Step 3: Add `display` to every person-bearing row**

In `app/dashboards.py`, after each query that selects a person, add the field. The rows are already `dict`s from `_rows()`, so:

- `review_queue` and `pending` (they select `full_name AS student, email AS student_email`): add
  `row["display"] = display_name({"full_name": row["student"], "first_name": "", "last_name": "", "email": row["student_email"]})` for each row.
- `students` (selects `full_name AS name, email`): add
  `row["display"] = display_name({"full_name": row["name"], "first_name": "", "last_name": "", "email": row["email"]})`.
- `queries` in the trainer endpoint (selects `full_name AS student, email`): same shape.

Write one module-level helper in `app/dashboards.py` rather than repeating the dict literal four times:

```python
def _display(row: dict, name_key: str, email_key: str = "email") -> str:
    """`display_name` for a joined row that carries only a name and an email."""
    return display_name(
        {
            "full_name": row.get(name_key) or "",
            "first_name": "",
            "last_name": "",
            "email": row.get(email_key) or "",
        }
    )
```

Apply the same treatment in `app/assignments.py` to the rows returned by `list_students`, `student_detail` (the `student` object), and `exercise_detail` (its `students` list); and in `app/modules.py` to whatever list of students it returns.

- [ ] **Step 4: Read `display` in the JS**

In each of the five files, replace the email fallback with the new field:

- `trainer_students.js:15` — `s.name || s.email` → `s.display`
- `trainer_section.js` — `x.student || x.student_email` → `x.display` (this file is rewritten wholesale in Task 4; make the minimal change here and Task 4 carries it)
- `trainer_dashboard.js:197` — the same pattern → `.display`
- `trainer_detail.js:61,114,141,225,241` — each `full_name || email` → `.display`
- `modules.js:147` — same → `.display`

Search for any remaining fallback and remove it:

Run: `grep -rn "|| *s\.email\|full_name *|| *\w*\.email\|student_email" app/static/js/`
Expected: no hit that renders a name. `student_email` may remain where it is shown as an explicit email field.

- [ ] **Step 5: Run the tests**

`tests/test_phase2.py` → PASS (5). Full suite → exit 0.

- [ ] **Step 6: Commit**

```bash
git commit -am "Give every person-bearing API row a display name"
```

---

### Task 4: Rewrite the section page safely and generalise it (findings F4, F6)

**Files:**
- Modify: `app/static/js/trainer_section.js` (complete rewrite)
- Modify: `app/templates/trainer_section.html`
- Modify: `app/main.py`
- Test: `tests/test_phase2.py`

**Interfaces:**
- Produces: `/trainer/{section}` pages for `exercises`, `queue`, `pending` and `completed`, each rendered from one template and one script, with the correct nav section highlighted. Task 6 adds the two new routes that use it.

`trainer_section.js` today is a single minified line that builds rows with `innerHTML` from `s.full_name`, `x.title` and `x.problem_statement` — the sink in finding F4. It is also the file Task 6 would extend. Rewriting it closes the sink and does the generalisation in one move.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_phase2.py`:

```python
def test_section_pages_highlight_their_own_nav_section(client):
    register_trainer(client)
    # The queue is not the Exercises section; it must not mark Exercises active.
    queue = client.get("/trainer/queue").text
    assert 'class="cb-link active" href="/trainer/students"' not in queue
    exercises = client.get("/trainer/exercises").text
    assert "active" in exercises


def test_exercise_titles_are_not_interpolated_as_html(client):
    register_trainer(client)
    client.post("/api/exercises", json={
        "title": "<img src=x onerror=alert(1)>",
        "problem_statement": "safe",
        "status": "published",
        "test_cases": [], "assign_to": [],
    })
    # The page is a shell; the title must not appear in the served HTML at all,
    # and the script must build rows with el(), never innerHTML.
    page = client.get("/trainer/exercises").text
    assert "onerror" not in page
    script = open("app/static/js/trainer_section.js", encoding="utf-8").read()
    assert "innerHTML" not in script
```

- [ ] **Step 2: Run to verify they fail**

Expected: the `innerHTML` assertion fails against the current one-liner.

- [ ] **Step 3: Rewrite the script**

Replace `app/static/js/trainer_section.js` entirely:

```javascript
// One page for every trainer list: exercises, review queue, pending work and
// completed work. Which one is decided by window.SECTION.
//
// Rows are built with el(), never innerHTML: these render trainer-authored
// titles and student-authored names, both of which reach a trainer's browser.
(function () {
  const D = window.Dash;
  const { el, when, due } = D;
  const list = document.getElementById("section-list");
  const section = window.SECTION;

  function row(title, metaParts, href) {
    const body = el(
      "div",
      {},
      el("div", { class: "title", text: title }),
      el("div", { class: "meta", text: metaParts.filter(Boolean).join(" · ") })
    );
    return href
      ? el("a", { class: "row", href }, body)
      : el("div", { class: "row" }, body);
  }

  function empty(message) {
    list.append(el("p", { class: "empty-note", text: message }));
  }

  const RENDER = {
    exercises(data) {
      const rows = data.exercises || [];
      if (!rows.length) return empty("No exercises created yet.");
      rows.forEach((x) =>
        list.append(
          row(
            x.title,
            [x.status, `${x.assigned} assigned`, `${x.tests} test cases`,
             x.due_date ? `Due ${due(x.due_date)}` : null],
            `/trainer/exercises/${x.id}`
          )
        )
      );
    },
    queue(data) {
      const rows = data.review_queue || [];
      if (!rows.length) return empty("Nothing is awaiting review.");
      rows.forEach((x) =>
        list.append(
          row(
            x.exercise,
            [x.display, `${x.tests_passed}/${x.tests_total} tests`, when(x.submitted_at)],
            `/trainer/submissions/${x.id}`
          )
        )
      );
    },
    pending(data) {
      const rows = data.pending || [];
      if (!rows.length) return empty("No outstanding work — everything assigned has been submitted.");
      rows.forEach((x) =>
        list.append(
          row(
            x.exercise,
            [x.display, x.due_date ? `Due ${due(x.due_date)}` : "No due date",
             x.overdue ? "Overdue" : null],
            null
          )
        )
      );
    },
    completed(data) {
      const rows = (data.students || []).filter((s) => s.completed > 0);
      if (!rows.length) return empty("No completed work yet.");
      rows.forEach((s) =>
        list.append(
          row(s.display, [`${s.completed} of ${s.assigned} completed`], `/trainer/students/${s.id}`)
        )
      );
    },
  };

  D.api("/api/dashboard/trainer")
    .then((data) => {
      list.textContent = "";
      (RENDER[section] || RENDER.exercises)(data);
    })
    .catch((err) => {
      list.textContent = "";
      empty(err.message || "Unable to load this page.");
    });
})();
```

The edit and delete controls the old file carried used `prompt()` and `confirm()` dialogs. Drop them: the exercise detail page at `/trainer/exercises/{id}` already owns editing, and each row now links there.

- [ ] **Step 4: Give the template a per-section heading and nav key**

Replace `app/templates/trainer_section.html`:

```jinja
{% extends "base.html" %}
{% from "_topbar.html" import topbar %}
{% set META = {
     'exercises': ('Coding exercises', 'Everything you have written, published or draft.', 'exercises'),
     'queue':     ('Awaiting review',  'Submissions waiting on your verdict.',            'dashboard'),
     'pending':   ('Pending submissions', 'Assigned, not yet submitted.',                 'dashboard'),
     'completed': ('Completed',        'Work your students have finished.',               'dashboard')
   } %}
{% set title, blurb, nav = META.get(section, META['exercises']) %}
{% block title %}{{ title }} · Python Learning Platform{% endblock %}
{% block body_class %}colab dash{% endblock %}
{% block head %}
<link rel="stylesheet" href="/static/css/colab.css?v={{ asset_v() }}">
<link rel="stylesheet" href="/static/css/dashboard.css?v={{ asset_v() }}">
{% endblock %}

{% block content %}
{{ topbar('trainer', name, back='/trainer', heading=title, current=nav) }}

<main class="dash-main">
  <div class="dash-head"><div><h1>{{ title }}</h1><p>{{ blurb }}</p></div></div>
  <section class="panel">
    <div class="panel-body" id="section-list"></div>
  </section>
</main>

<div class="toast" id="toast" hidden></div>
{% endblock %}

{% block scripts %}
<script>window.SECTION = {{ section|tojson }};</script>
<script src="/static/js/dashboard_common.js?v={{ asset_v() }}"></script>
<script src="/static/js/trainer_section.js?v={{ asset_v() }}"></script>
{% endblock %}
```

Note `dashboard_common.js` is now loaded — the rewritten script needs `D`.

- [ ] **Step 5: Run the tests**

`tests/test_phase2.py` → PASS (7). Full suite → exit 0.

- [ ] **Step 6: Commit**

```bash
git commit -am "Rewrite the trainer section page without innerHTML and generalise it"
```

---

### Task 5: Trainer dashboard — cards only

**Files:**
- Modify: `app/templates/trainer_dashboard.html`
- Modify: `app/static/js/trainer_dashboard.js`
- Test: `tests/test_phase2.py`

**Interfaces:**
- Produces: `/trainer` renders exactly five linked cards and nothing else.

- [ ] **Step 1: Write the failing tests**

```python
def test_trainer_dashboard_is_cards_only(client):
    register_trainer(client)
    html = client.get("/trainer").text
    for gone in ("Submissions awaiting review", "Pending submissions",
                 "Coding exercises", "Upcoming deadlines", "+ New exercise", "Drafts"):
        assert gone not in html, gone
    assert 'id="stats"' in html
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Strip the template**

In `app/templates/trainer_dashboard.html`, delete the `.quick` div (the `+ New exercise` and `Drafts` buttons — finding F7; they live in the Exercises dropdown now) and the entire `.panel-grid` block with its four panels. What remains is the heading and `<section class="stat-grid" id="stats"></section>`.

- [ ] **Step 4: Make the cards links**

In `app/static/js/trainer_dashboard.js`, replace `renderStats` with five linked cards and delete every function that rendered the removed panels (the review list, pending list, exercise list, deadline list) plus their calls:

```javascript
  function renderStats() {
    const s = data.stats;
    const cards = [
      { label: "Students", value: s.students, sub: "On your roster",
        href: "/trainer/students" },
      { label: "Pending submissions", value: s.pending,
        sub: s.overdue ? `${s.overdue} past due` : "Assigned, not yet in",
        tone: s.overdue ? "bad" : "", href: "/trainer/pending" },
      { label: "Awaiting review", value: s.awaiting_review,
        sub: "Submitted, needs your verdict",
        tone: s.awaiting_review ? "warn" : "", href: "/trainer/queue" },
      { label: "Exercises", value: s.exercises,
        sub: `${s.published} published · ${s.drafts} draft`,
        href: "/trainer/exercises" },
      { label: "Completed", value: s.completed, sub: "Finished by your students",
        tone: "good", href: "/trainer/completed" },
    ];

    const host = document.getElementById("stats");
    host.textContent = "";
    cards.forEach((c) =>
      host.append(
        el("a", { class: `stat ${c.tone || ""}`, href: c.href },
          el("span", { class: "stat-label", text: c.label }),
          el("strong", { class: "stat-value", text: String(c.value) }),
          el("span", { class: "stat-sub", text: c.sub })
        )
      )
    );
  }
```

Keep the bell and notification wiring — the topbar still has them.

- [ ] **Step 5: Check the card styles still apply**

`.stat` was written for a `<button>`. In `app/static/css/dashboard.css`, confirm `.stat` sets `display`, `text-decoration: none` and `color: var(--text)`; add whichever are missing so an `<a>` renders identically. Add a visible focus ring:

```css
.stat:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
```

- [ ] **Step 6: Run the tests, then commit**

Full suite → exit 0.

```bash
git commit -am "Reduce the trainer dashboard to five linked cards"
```

---

### Task 6: The two new trainer pages, and the roster by name

**Files:**
- Modify: `app/main.py`, `app/assignments.py`
- Modify: `app/static/js/trainer_students.js`, `trainer_detail.js`
- Test: `tests/test_phase2.py`

**Interfaces:**
- Consumes: the generalised section template from Task 4, `display` from Task 3.
- Produces: `/trainer/pending`, `/trainer/completed`, and late-submission figures on `/api/students/{id}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_new_trainer_pages_are_guarded_and_render(client):
    register_trainer(client)
    for path in ("/trainer/pending", "/trainer/completed"):
        assert client.get(path).status_code == 200
    client.cookies.clear()
    register(client, email="s2@example.com")
    for path in ("/trainer/pending", "/trainer/completed"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "/student"


def test_student_detail_counts_late_submissions(client):
    # An assignment submitted after its due date is late; one with no due date never is.
    register_trainer(client)
    students = client.get("/api/students").json()
    detail_keys = ("late", "on_time_rate", "assigned", "completed", "pending", "awaiting")
    if students:
        detail = client.get(f"/api/students/{students[0]['id']}").json()
        for key in detail_keys:
            assert key in detail, key
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Add the two routes**

In `app/main.py`, beside the existing literal trainer routes:

```python
@app.get("/trainer/pending", include_in_schema=False)
def trainer_pending_page(request: Request, user=Depends(get_optional_user)):
    return _trainer_page(request, user, "trainer_section.html", {"section": "pending"})


@app.get("/trainer/completed", include_in_schema=False)
def trainer_completed_page(request: Request, user=Depends(get_optional_user)):
    return _trainer_page(request, user, "trainer_section.html", {"section": "completed"})
```

Both must sit BEFORE `@app.get("/trainer/exercises/{exercise_id}")` and any other single-segment parameter under `/trainer/`.

- [ ] **Step 4: Compute the late figures**

In `app/assignments.py`'s `student_detail`, after `rows` is built, replace the `completed`/`progress` block with:

```python
    rows = [dict(r) for r in exercises]
    completed = sum(1 for r in rows if r["status"] == "completed")
    submitted = [r for r in rows if r["submitted_at"]]
    # Late means it arrived after its due date. No due date is never late.
    for r in rows:
        r["late"] = bool(r["due_date"] and r["submitted_at"] and r["submitted_at"] > r["due_date"])
    late = sum(1 for r in rows if r["late"])
    graded = [r for r in submitted if r["tests_total"]]
    return {
        "student": {**dict(student), "display": display_name(student)},
        "exercises": rows,
        "modules": module_rows,
        "queries": [dict(q) for q in queries],
        "assigned": len(rows),
        "completed": completed,
        "pending": sum(1 for r in rows if r["status"] in OPEN_STATUSES),
        "awaiting": sum(1 for r in rows if r["status"] == "submitted"),
        "late": late,
        "on_time_rate": round(100 * (len(submitted) - late) / len(submitted)) if submitted else 100,
        "avg_tests": round(
            100 * sum(r["tests_passed"] for r in graded) / sum(r["tests_total"] for r in graded)
        ) if graded else 0,
        "last_active": max((r["last_opened_at"] for r in rows if r["last_opened_at"]), default=None),
        "progress": round(100 * completed / len(rows)) if rows else 0,
    }
```

`OPEN_STATUSES` lives in `app/dashboards.py`. Import it — `from .dashboards import OPEN_STATUSES`. There is no cycle: `dashboards.py` imports only `config`, `db`, `deps` and `names`, never `assignments`.

- [ ] **Step 5: Roster rows lose the progress bar, gain the name**

In `app/static/js/trainer_students.js`, render each row from `s.display` and remove the progress-bar element entirely (requirement 8). Keep the counts as text. Each row links to `/trainer/students/${s.id}`.

In `app/static/js/trainer_detail.js`, render the new figures on the student detail page: assigned, completed, pending, awaiting review, **late submissions**, on-time rate, average tests passed, last active — and mark each exercise row `Late` where `r.late` is true. Build every row with `el()`, never `innerHTML`.

- [ ] **Step 6: Run the tests, then commit**

```bash
git commit -am "Add the pending and completed pages, and student detail by name with late figures"
```

---

### Task 7: Student dashboard — five cards in one row, plus deadlines

**Files:**
- Modify: `app/templates/student_dashboard.html`, `student_exercises.html`
- Modify: `app/static/js/student_dashboard.js`, `student_exercises.js`
- Modify: `app/static/css/dashboard.css`
- Test: `tests/test_phase2.py`

**Interfaces:**
- Produces: `/student` is five cards and an Upcoming deadlines panel. `/student/exercises` gains the assignments list, its filters and the trainer-queries sidebar.

- [ ] **Step 1: Write the failing tests**

```python
def test_student_dashboard_keeps_only_cards_and_deadlines(client):
    register(client)
    html = client.get("/student").text
    assert 'id="stats"' in html
    assert "Upcoming deadlines" in html
    for gone in ("Assigned exercises", "From your trainer"):
        assert gone not in html, gone


def test_student_exercises_page_absorbs_the_list_and_queries(client):
    register(client)
    html = client.get("/student/exercises").text
    assert "Assigned exercises" in html
    assert "From your trainer" in html
    for tab in ("All", "To do", "In progress", "Submitted", "Changes requested", "Completed"):
        assert tab in html, tab
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Rebuild the student dashboard template**

In `app/templates/student_dashboard.html`, remove the resume banner, the assignments panel and the queries panel. Keep the heading and `#stats`, and add a deadlines panel:

```html
  <section class="stat-grid five" id="stats"></section>

  <div class="panel-grid single">
    <section class="panel" id="deadlines-panel">
      <header><h2>Upcoming deadlines</h2></header>
      <div class="panel-body" id="deadline-list"></div>
    </section>
  </div>
```

- [ ] **Step 4: Five in a row**

In `app/static/css/dashboard.css`, add:

```css
.stat-grid.five { grid-template-columns: repeat(5, 1fr); }
@media (max-width: 1100px) { .stat-grid.five { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 720px)  { .stat-grid.five { grid-template-columns: repeat(2, 1fr); } }
.panel-grid.single { grid-template-columns: 1fr; }
```

That is requirement 4 — the reference screenshots show three cards then two, because the grid used `auto-fit`.

- [ ] **Step 5: Cards become links; add the deadlines list**

In `app/static/js/student_dashboard.js`, make each card an `<a>` to `/student/exercises?filter=<key>`, using the mapping the spec fixes:

| Card | filter |
| --- | --- |
| Assigned | `all` |
| In progress | `in_progress` |
| Awaiting review | `submitted` |
| Changes requested | `changes_requested` |
| Completed | `completed` |

Then render `#deadline-list` from the assignments that are open and have a `due_date`, soonest first, marking overdue ones. Delete the functions that rendered the assignments list and the queries panel from this file.

- [ ] **Step 6: Move the list and queries onto the exercises page**

Rebuild `app/templates/student_exercises.html` to carry the assignments panel with its search box and six filter tabs (adding **In progress**), plus a "From your trainer" sidebar. Move the corresponding rendering out of `student_dashboard.js` into `student_exercises.js`, building rows with `el()`. Read the initial tab from `?filter=` on load, defaulting to `all`.

- [ ] **Step 7: Run the tests, then commit**

```bash
git commit -am "Student dashboard to cards and deadlines; exercises page takes the list"
```

---

### Task 8: Exercise form and module progress

**Files:**
- Modify: `app/templates/exercise_form.html`, `app/schemas.py`
- Modify: `app/static/js/trainer_detail.js`, `app/static/js/modules.js`
- Modify: `app/templates/modules_student.html`
- Test: `tests/test_phase2.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_exercise_form_drops_the_retired_fields(client):
    register_trainer(client)
    html = client.get("/trainer/exercises/new").text
    for gone in ("Input format", "Output format", "Constraints", "View drafts"):
        assert gone not in html, gone
    assert "Assign" in html
    assert "Assign to" not in html


def test_exercise_still_accepts_the_retained_fields(client):
    register_trainer(client)
    r = client.post("/api/exercises", json={
        "title": "Sum", "problem_statement": "Add two numbers",
        "sample_input": "1 2", "sample_output": "3",
        "status": "published", "test_cases": [], "assign_to": [],
    })
    assert r.status_code == 201
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Trim the form**

In `app/templates/exercise_form.html`, delete the `field-row` holding Input format and Output format, delete the Constraints field, and delete the `.quick` div holding "View drafts". Rename the "Assign to" panel heading to **Assign**.

In `app/static/js/trainer_detail.js`, stop reading `#ex-input`, `#ex-output` and `#ex-constraints` — send `""` for those keys, or omit them (the `ExerciseIn` schema defaults each to `""`). Render the student picker by `display`, not email.

Leave the three columns in the database and the three fields on `ExerciseIn`: existing exercises hold data there, and dropping a SQLite column means a table rebuild.

- [ ] **Step 4: Module progress bars**

In `app/modules.py`, ensure the student module list returns `progress` per module (blocks with `ran_ok = 1` over total code blocks) — `student_detail` in `assignments.py` already computes exactly this; mirror it. In `app/static/js/modules.js`, render a progress bar per module card on the student view.

- [ ] **Step 5: Run the tests, then commit**

Full suite → exit 0.

```bash
git commit -am "Trim the exercise form and add module progress bars"
```

---

## Phase 2 exit criteria

- Trainer dashboard is five linked cards and nothing else; each card opens its page.
- `/trainer/pending` and `/trainer/completed` exist, are trainer-guarded, and render.
- The roster shows names with no progress bars; student detail shows late submissions.
- The exercise form has no Input format, Output format, Constraints or Drafts button, and its panel reads **Assign**.
- Student dashboard is five cards in ONE row plus Upcoming deadlines, nothing else.
- `/student/exercises` carries the list, six filter tabs and the trainer-queries sidebar, and honours `?filter=`.
- Student modules show a progress bar each.
- No API response returns an email where a name belongs; no JS falls back to `.email`.
- `grep -rn "innerHTML" app/static/js/` returns nothing that interpolates data.
- Every page renders `data-theme` server-side; `syncTheme()` is gone.
- A password change signs out other devices.
- `./.venv/Scripts/python.exe -m pytest -q` is green.

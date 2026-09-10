# Sidebar Shell and Redesigned Dashboards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the whole app onto a left-sidebar shell, redesign both dashboards around stat cards + a deadline calendar + the user's own activity, and split "what I did" (activity) from "what happened to me" (notifications, with a full history page).

**Architecture:** The `topbar()` macro in `_topbar.html` keeps its exact name and signature and changes only what it emits — a fixed sidebar plus a slimmer header — so all 21 calling templates pick up the new layout with no edit. One CSS rule, `body:has(.app-sidebar) { padding-left: var(--sidebar-w) }`, supplies the geometry. The activity/notification split is a one-clause change to `ACTIVITY_SELECT`. Two new read endpoints (`/api/search`, paged notifications); no schema changes anywhere.

**Tech Stack:** FastAPI, Jinja2, SQLite (`sqlite3`, no ORM), Pydantic v2, vanilla JavaScript (no build step), pytest + `fastapi.testclient`.

**Spec:** `docs/superpowers/specs/2026-09-10-sidebar-dashboards-design.md`

## Global Constraints

- Run everything through `.venv\Scripts\python.exe`, never bare `python`. `python3` does not exist on this machine.
- Tests: `.venv\Scripts\python.exe -m pytest`. `tests/conftest.py` points the app at a throwaway DB and must not be bypassed. The full suite takes >120s — run targeted files while working, the whole suite before declaring a task done.
- **No schema changes.** `activities` and `notifications` already carry every field needed. If you think you need a column, stop and re-read the spec.
- No new runtime dependencies. No build step for CSS or JS.
- Static URLs are cache-busted: always `/static/...?v={{ asset_v() }}`.
- Page routes live in `app/main.py` and must be declared as **literal** paths before any single-segment path parameter that would swallow them. `main.py` carries a comment about the `/trainer/{section}` bug this caused before.
- CSS tokens are defined on `:root` in `app/static/css/styles.css` and swap under `[data-theme]`. Never hardcode a colour; add a token if one is missing.
- The three theme values are exactly `system`, `light`, `dark`.
- Commit after every task.

---

## File Structure

**Created:**
- `app/search.py` — the `/api/search` router. Its own module because it queries across exercises, modules and users, and belongs to none of them.
- `app/templates/notifications.html` — the notification history page shell.
- `app/static/js/notifications.js` — history page behaviour (paging, absolute timestamps).
- `app/static/css/shell.css` — sidebar, header and search styles. Kept separate from `dashboard.css` so the shell can be reverted or restyled without touching panel styles.
- `tests/test_shell.py` — sidebar renders for both roles on every page type.
- `tests/test_search.py` — search results and authorisation.
- `tests/test_notifications_page.py` — history endpoint and paging.

**Modified:**
- `app/templates/_topbar.html` — macro emits sidebar + header. Same signature.
- `app/templates/base.html` — load `shell.css`.
- `app/templates/trainer_dashboard.html`, `student_dashboard.html` — panel order, calendar panel.
- `app/templates/student_exercises.html`, `trainer_section.html` — deadline dropdown.
- `app/dashboards.py` — `ACTIVITY_SELECT` scoping; paged notifications endpoint.
- `app/main.py` — `/notifications` page route; register the search router.
- `app/static/css/dashboard.css` — pastel stat cards, calendar panel.
- `app/static/js/dashboard_common.js` — calendar renderer, bell "See all" footer.
- `app/static/js/trainer_dashboard.js`, `student_dashboard.js` — render calendar instead of the deadline list.
- `app/static/js/student_exercises.js`, `trainer_section.js` — deadline filter.
- `tests/test_dashboards.py` — activity scoping assertions.

---

### Task 1: Sidebar shell

**Files:**
- Create: `app/static/css/shell.css`, `tests/test_shell.py`
- Modify: `app/templates/_topbar.html`, `app/templates/base.html`

**Interfaces:**
- Consumes: nothing.
- Produces: `.app-sidebar` (nav landmark), `.app-header` (search + bell + profile). Element ids `bell-btn`, `bell-panel`, `bell-badge`, `bell-list`, `bell-foot`, `profile-menu`, `profile-panel`, `logout-btn` are **preserved exactly** — `dashboard_common.js` and the macro's inline script find them by id.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_shell.py
"""The sidebar shell, which every signed-in page renders through topbar()."""

from conftest import register, register_trainer


def test_the_trainer_sidebar_carries_every_nav_item(client):
    register_trainer(client)
    html = client.get("/trainer").text
    assert 'class="app-sidebar"' in html
    for label in ("Dashboard", "Exercises", "Modules", "Students", "Online session"):
        assert label in html


def test_the_student_sidebar_has_no_students_link(client):
    register(client)
    html = client.get("/student").text
    assert 'class="app-sidebar"' in html
    assert 'href="/trainer/students"' not in html


def test_the_bell_and_profile_moved_into_the_header_intact(client):
    """Their ids are the contract dashboard_common.js relies on."""
    register_trainer(client)
    html = client.get("/trainer").text
    for element_id in ("bell-btn", "bell-panel", "bell-badge", "bell-list",
                       "profile-menu", "profile-panel", "logout-btn"):
        assert f'id="{element_id}"' in html


def test_the_login_page_has_no_sidebar(client):
    """login.html does not call topbar(); the auth page must stay untouched."""
    assert 'class="app-sidebar"' not in client.get("/login").text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_shell.py -v`
Expected: FAIL on `'class="app-sidebar"' in html` — the class does not exist yet.

- [ ] **Step 3: Rewrite the macro's markup**

In `app/templates/_topbar.html`, keep the `{% macro topbar(role, name, back=None, heading=None, bell=False, current=None) %}` line and the `{% set %}` lines exactly as they are. Replace the `<header class="cb-topbar">` element with:

```jinja
<aside class="app-sidebar">
  <a class="cb-brand" href="{{ home }}">
    <span class="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
           stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="9 8 5 12 9 16"></polyline>
        <polyline points="15 8 19 12 15 16"></polyline>
      </svg>
    </span>
    <span class="cb-title">Python Learning Platform</span>
  </a>

  <nav class="side-nav">
    <a class="side-link {{ 'active' if current == 'dashboard' }}" href="{{ home }}">
      <span class="ico" aria-hidden="true">▦</span><span>Dashboard</span>
    </a>
    {% if role == 'trainer' %}
      <a class="side-link {{ 'active' if current == 'exercises' }}" href="/trainer/exercises">
        <span class="ico" aria-hidden="true">▤</span><span>Exercises</span>
      </a>
      <a class="side-link {{ 'active' if current == 'modules' }}" href="/trainer/modules">
        <span class="ico" aria-hidden="true">▥</span><span>Modules</span>
      </a>
      <a class="side-link {{ 'active' if current == 'students' }}" href="/trainer/students">
        <span class="ico" aria-hidden="true">▧</span><span>Students</span>
      </a>
    {% else %}
      <a class="side-link {{ 'active' if current == 'exercises' }}" href="/student/exercises">
        <span class="ico" aria-hidden="true">▤</span><span>Exercises</span>
      </a>
      <a class="side-link {{ 'active' if current == 'modules' }}" href="/student/modules">
        <span class="ico" aria-hidden="true">▥</span><span>Modules</span>
      </a>
    {% endif %}
    <span class="side-link disabled" aria-disabled="true" title="Coming soon">
      <span class="ico" aria-hidden="true">▨</span><span>Online session</span>
      <span class="soon">Soon</span>
    </span>
  </nav>
</aside>

<header class="app-header">
  {% if back %}<a class="cb-btn ghost back-btn" href="{{ back }}">← Back</a>{% endif %}
  {% if heading %}<span class="cb-heading">{{ heading }}</span>{% endif %}

  <div class="header-search">
    <input type="search" id="global-search" placeholder="Search anything…"
           autocomplete="off" aria-label="Search">
    <div class="search-results" id="search-results" hidden></div>
  </div>

  <div class="cb-spacer"></div>
```

Then keep the existing `{% if bell %}…{% endif %}` block and the entire `<div class="avatar-wrap">…</div>` block **exactly as they are**, and close with `</header>`. Keep the inline `<script>` at the end of the macro unchanged.

- [ ] **Step 4: Write the shell stylesheet**

Create `app/static/css/shell.css`:

```css
/* The sidebar shell. Every page that calls topbar() gets this; login.html,
   which does not call it, is untouched. The layout is supplied by one rule
   below rather than by wrapping 21 templates in a flex container. */
:root { --sidebar-w: 232px; }

body:has(.app-sidebar) { padding-left: var(--sidebar-w); }

.app-sidebar {
  position: fixed; inset: 0 auto 0 0; width: var(--sidebar-w);
  display: flex; flex-direction: column; gap: 4px;
  padding: 18px 12px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  z-index: 30;
}
.app-sidebar .cb-brand { margin: 0 8px 18px; }

.side-nav { display: flex; flex-direction: column; gap: 2px; }
.side-link {
  display: flex; align-items: center; gap: 11px;
  padding: 10px 12px; border-radius: 10px;
  color: var(--text-dim); text-decoration: none;
  font-size: 14px; font-weight: 500;
}
.side-link:hover { background: var(--cell-bg); color: var(--text); }
.side-link.active { background: var(--accent-soft, var(--cell-bg)); color: var(--accent-fill); }
.side-link.disabled { opacity: .55; cursor: default; }
.side-link .ico { font-size: 15px; width: 18px; text-align: center; }
.side-link .soon { margin-left: auto; font-size: 10px; opacity: .8; }

.app-header {
  display: flex; align-items: center; gap: 14px;
  padding: 14px 26px;
  border-bottom: 1px solid var(--border);
  background: var(--bg);
}
.header-search { position: relative; flex: 0 1 420px; }
.header-search input {
  width: 100%; padding: 9px 14px;
  border: 1px solid var(--border); border-radius: 999px;
  background: var(--surface); color: var(--text); font-size: 13.5px;
}
.header-search input:focus { outline: 2px solid var(--blue); outline-offset: 1px; }
.search-results {
  position: absolute; top: calc(100% + 6px); left: 0; right: 0;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; box-shadow: var(--shadow-card);
  max-height: 340px; overflow: auto; z-index: 40; padding: 6px;
}

/* Icon rail, then off-canvas. The brand label and link text go first because
   they are what stops fitting; the icons stay legible on their own. */
@media (max-width: 1000px) {
  :root { --sidebar-w: 64px; }
  .app-sidebar .cb-title, .side-link span:not(.ico):not(.soon),
  .side-link .soon { display: none; }
  .side-link { justify-content: center; }
}
@media (max-width: 700px) {
  body:has(.app-sidebar) { padding-left: 0; }
  .app-sidebar { transform: translateX(-100%); transition: transform .18s; }
  .app-sidebar.open { transform: none; }
  .header-search { flex: 1 1 auto; }
}
```

- [ ] **Step 5: Load the stylesheet**

In `app/templates/base.html`, after the existing `styles.css` link:

```jinja
  <link rel="stylesheet" href="/static/css/shell.css?v={{ asset_v() }}">
```

- [ ] **Step 6: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_shell.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 7: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS. Any failure here is a template that asserted on `cb-topbar` or `cb-nav`; update the assertion, not the markup.

- [ ] **Step 8: Look at it**

Start the server (`.\run.ps1`), sign in as trainer and as student, and look at `/trainer`, `/student`, `/trainer/exercises`, `/trainer/modules`, `/student/modules`, and one deep page (`/trainer/students/<id>`). Confirm: no content sits under the sidebar, the back button and heading still appear where a page passes them, and `/login` is unchanged.

- [ ] **Step 9: Commit**

```bash
git add app/templates/_topbar.html app/templates/base.html app/static/css/shell.css tests/test_shell.py
git commit -m "feat: move the app onto a left sidebar shell"
```

---

### Task 2: Pastel stat cards

**Files:**
- Modify: `app/static/css/dashboard.css`

**Interfaces:**
- Consumes: the `.stat-grid` markup already emitted by `trainer_dashboard.js` and `student_dashboard.js`.
- Produces: nothing new. CSS only — no JS or template change, so no test.

- [ ] **Step 1: Add the tint tokens**

In `app/static/css/styles.css`, inside `:root`, after `--amber`:

```css
  --tint-violet: #2a2445;
  --tint-blue:   #17293f;
  --tint-green:  #16301f;
  --tint-rose:   #3a1f24;
  --tint-amber:  #37301a;
```

And in the light-theme block, after its `--cell-bg`:

```css
  --tint-violet: #eeebff;
  --tint-blue:   #e6f0ff;
  --tint-green:  #e6f6ec;
  --tint-rose:   #ffecec;
  --tint-amber:  #fff4e0;
```

- [ ] **Step 2: Restyle the cards**

In `app/static/css/dashboard.css`, find the existing `.stat-grid` rules and add after them:

```css
/* Reference styling: soft tinted cards, rounded, icon over a big number.
   Colour cycles by position so a dashboard with four cards and one with five
   both read as a set. */
.stat-grid > * {
  border-radius: 16px;
  border: 1px solid transparent;
  padding: 18px 18px 16px;
  transition: transform .12s, box-shadow .12s;
}
.stat-grid > *:hover { transform: translateY(-2px); box-shadow: var(--shadow-card-hover); }
.stat-grid > *:nth-child(5n+1) { background: var(--tint-violet); }
.stat-grid > *:nth-child(5n+2) { background: var(--tint-blue); }
.stat-grid > *:nth-child(5n+3) { background: var(--tint-green); }
.stat-grid > *:nth-child(5n+4) { background: var(--tint-rose); }
.stat-grid > *:nth-child(5n+5) { background: var(--tint-amber); }
```

- [ ] **Step 3: Look at it in both themes**

Load `/trainer` and `/student`. Toggle theme in Settings. Confirm the numbers stay readable on every tint in **both** light and dark — this is the failure mode of tinted cards, and the reason the tokens are theme-swapped rather than fixed pastels.

- [ ] **Step 4: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/static/css/styles.css app/static/css/dashboard.css
git commit -m "feat: restyle dashboard stat cards as tinted panels"
```

---

### Task 3: Recent activity shows only your own actions

**Files:**
- Modify: `app/dashboards.py:34-43`
- Test: `tests/test_dashboards.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ACTIVITY_SELECT` gains `AND a.actor_id = a.user_id`. Both `_feed()` and `full_activity()` use this constant, so both change together.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dashboards.py`:

```python
def test_recent_activity_shows_only_what_you_did_yourself(client):
    """A trainer's feed is their own actions. A student submitting is something
    that happened TO the trainer, so it belongs in notifications, not here."""
    register_trainer(client)
    trainer_id = client.get("/auth/me").json()["id"]

    from app.db import get_conn, record_activity, notify, utcnow
    with get_conn() as conn:
        student = conn.execute(
            "INSERT INTO users (email, password_hash, created_at, role, full_name)"
            " VALUES ('someone@example.com', 'x', ?, 'student', 'Some One')",
            (utcnow(),),
        ).lastrowid
        record_activity(conn, trainer_id, "created", "You created an exercise",
                        trainer_id, "/trainer")
        record_activity(conn, trainer_id, "submitted", "Some One submitted work",
                        int(student), "/trainer")
        notify(conn, trainer_id, "submitted", "Some One submitted work", "/trainer")

    data = client.get("/api/dashboard/trainer").json()
    summaries = [a["summary"] for a in data["activity"]]
    assert "You created an exercise" in summaries
    assert "Some One submitted work" not in summaries
    assert "Some One submitted work" in [n["title"] for n in data["notifications"]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_dashboards.py::test_recent_activity_shows_only_what_you_did_yourself -v`
Expected: FAIL on `"Some One submitted work" not in summaries` — the other person's action is currently in the feed.

- [ ] **Step 3: Scope the query**

In `app/dashboards.py`, change the `ACTIVITY_SELECT` constant's `WHERE` clause and its comment:

```python
# Recent activity is what YOU did. Something another person did to you -- a
# trainer approving your work, a student submitting -- is a notification, and
# is already written to `notifications` as well, so nothing is lost by keeping
# it out of here. The actor join stays: `kind` and the actor's role still
# describe the row, and full_activity() shares this constant.
ACTIVITY_SELECT = """
    SELECT a.id, a.kind, a.summary, a.link, a.created_at, a.actor_id,
           u.role AS actor_role, u.full_name AS actor_full_name,
           u.first_name AS actor_first_name, u.last_name AS actor_last_name,
           u.email AS actor_email
    FROM activities a
    LEFT JOIN users u ON u.id = a.actor_id
    WHERE a.user_id = ? AND a.actor_id = a.user_id
    ORDER BY a.created_at DESC, a.id DESC
"""
```

- [ ] **Step 4: Fix `activity_total` to match**

Still in `app/dashboards.py`, in `_feed()`, the total must count the same rows the feed returns or the pager will offer pages that render empty:

```python
        "activity_total": _scalar(
            conn,
            "SELECT COUNT(*) FROM activities WHERE user_id = ? AND actor_id = user_id",
            (user_id,),
        ),
```

- [ ] **Step 5: Run the test**

Run: `.venv\Scripts\python.exe -m pytest tests/test_dashboards.py -v`
Expected: PASS. Existing tests that asserted another person's action appears in `activity` will now fail — each one is a deliberate inversion: change it to assert the row is in `notifications` instead. Do not delete the assertion.

- [ ] **Step 6: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/dashboards.py tests/test_dashboards.py
git commit -m "feat: recent activity shows only the viewer's own actions"
```

---

### Task 4: Calendar panel with deadline dots

**Files:**
- Modify: `app/templates/trainer_dashboard.html:26-31`, `app/templates/student_dashboard.html:25-30`, `app/static/js/dashboard_common.js`, `app/static/js/trainer_dashboard.js:45-70`, `app/static/js/student_dashboard.js:72-90`, `app/static/css/dashboard.css`

**Interfaces:**
- Consumes: `data.deadlines` — the array both dashboard endpoints already return, each item having `id`, `title`, `due_date` (ISO 8601 string) and `overdue`. **There is no `link` field, and `id` means different things per role**: the trainer query selects `e.id` (an exercise), the student query selects `a.id` (an assignment). The caller therefore supplies the link builder.
- Produces: `renderCalendar(hostId, deadlines, monthDate, linkFor)` exported from `dashboard_common.js`, where `linkFor(item)` returns the href for a dated item.

- [ ] **Step 1: Swap the panels in both templates**

In `app/templates/trainer_dashboard.html`, replace the `deadlines-panel` section with:

```jinja
    <section class="panel" id="calendar-panel">
      <header>
        <h2>Calendar</h2>
        <span class="spacer"></span>
        <button class="cb-btn ghost" id="cal-prev" aria-label="Previous month">‹</button>
        <span class="cal-label" id="cal-label"></span>
        <button class="cb-btn ghost" id="cal-next" aria-label="Next month">›</button>
      </header>
      <div class="panel-body" id="calendar"></div>
    </section>
```

Then move the whole `activity-panel` section up so it sits beside the calendar in the same two-column row, replacing `sessions-panel`. Delete `sessions-panel`. Apply the identical change to `app/templates/student_dashboard.html`.

- [ ] **Step 2: Write the calendar renderer**

In `app/static/js/dashboard_common.js`, before the module's return/export block:

```js
  // Month grid with a dot on any date carrying a deadline. Deliberately not a
  // list: deadlines are actionable on the Exercises page, and here they are
  // only a glance at where the month is busy.
  function renderCalendar(hostId, deadlines, monthDate, linkFor) {
    const host = document.getElementById(hostId);
    if (!host) return;
    const base = monthDate || new Date();
    const year = base.getFullYear();
    const month = base.getMonth();

    const byDay = new Map();
    (deadlines || []).forEach((d) => {
      const due = new Date(d.due_date);
      if (due.getFullYear() !== year || due.getMonth() !== month) return;
      const day = due.getDate();
      if (!byDay.has(day)) byDay.set(day, []);
      byDay.get(day).push(d);
    });

    const label = document.getElementById("cal-label");
    if (label) {
      label.textContent = base.toLocaleDateString(undefined, {
        month: "long", year: "numeric",
      });
    }

    const first = new Date(year, month, 1).getDay();
    const days = new Date(year, month + 1, 0).getDate();
    const today = new Date();
    const isThisMonth =
      today.getFullYear() === year && today.getMonth() === month;

    host.textContent = "";
    const grid = el("div", { class: "cal-grid" });
    ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].forEach((d) =>
      grid.append(el("span", { class: "cal-head" }, d))
    );
    for (let i = 0; i < first; i += 1) grid.append(el("span", { class: "cal-pad" }));

    for (let day = 1; day <= days; day += 1) {
      const hits = byDay.get(day) || [];
      const cell = el(
        "span",
        {
          class:
            "cal-day" +
            (isThisMonth && today.getDate() === day ? " today" : "") +
            (hits.length ? " has-due" : ""),
        },
        String(day)
      );
      if (hits.length) {
        cell.append(el("i", { class: "cal-dot", "aria-hidden": "true" }));
        cell.title = hits.map((h) => h.title).join(", ");
        cell.style.cursor = "pointer";
        cell.addEventListener("click", () => {
          if (linkFor) window.location.href = linkFor(hits[0]);
        });
      }
      grid.append(cell);
    }
    host.append(grid);
  }
```

Add `renderCalendar` to the object the module returns, alongside `renderNotifications` and `renderActivity`.

- [ ] **Step 3: Call it from both dashboards**

In `app/static/js/trainer_dashboard.js`, delete the "upcoming deadlines" block (lines 45-70) and in its place:

```js
  // Calendar replaces the deadline list (spec: deadlines are a glance here and
  // actionable on the Exercises page). The trainer's deadline rows carry an
  // EXERCISE id, so the link differs from the student's.
  let calMonth = new Date();
  function paintCalendar() {
    if (!data) return;
    D.renderCalendar("calendar", data.deadlines, calMonth,
                     (d) => `/trainer/exercises/${d.id}`);
  }
```

`data` is the module-level payload variable already declared at `trainer_dashboard.js:9` (`let data = null;`) — do not introduce a new one. Call `paintCalendar()` where the old deadline render was called, and wire the month buttons after first paint:

```js
  document.getElementById("cal-prev").addEventListener("click", () => {
    calMonth = new Date(calMonth.getFullYear(), calMonth.getMonth() - 1, 1);
    paintCalendar();
  });
  document.getElementById("cal-next").addEventListener("click", () => {
    calMonth = new Date(calMonth.getFullYear(), calMonth.getMonth() + 1, 1);
    paintCalendar();
  });
```

Apply the same change to `app/static/js/student_dashboard.js`, with one difference: the student's deadline rows carry an **assignment** id, so its link builder is `(d) => \`/student/assignments/${d.id}/solve\``. Check that file's own payload variable name before assuming it is also called `data`.

- [ ] **Step 4: Style the grid**

Append to `app/static/css/dashboard.css`:

```css
/* Deadline calendar. Seven columns, dots not badges: the count is not the
   point, the shape of the month is. */
.cal-grid {
  display: grid; grid-template-columns: repeat(7, 1fr);
  gap: 2px; text-align: center;
}
.cal-head {
  padding: 8px 0; font-size: 11px; font-weight: 600;
  letter-spacing: .04em; text-transform: uppercase; color: var(--text-dim);
}
.cal-day {
  position: relative; padding: 10px 0; border-radius: 9px;
  font-size: 13.5px; color: var(--text);
}
.cal-day.today { background: var(--accent-fill); color: var(--on-accent); font-weight: 600; }
.cal-day.has-due:hover { background: var(--cell-bg); }
.cal-dot {
  position: absolute; left: 50%; bottom: 5px; transform: translateX(-50%);
  width: 5px; height: 5px; border-radius: 50%; background: var(--blue-dark);
}
.cal-day.today .cal-dot { background: var(--on-accent); }
.cal-label { font-size: 13px; color: var(--text-dim); min-width: 120px; }
```

- [ ] **Step 5: Look at it**

Load `/trainer`. The seeded data has three exercises with deadlines in September 2026, one overdue — confirm dots land on the right dates, that today is highlighted, that the month arrows move the grid, and that clicking a dot opens the exercise.

- [ ] **Step 6: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS. A test asserting `deadline-list` or "Upcoming deadlines" must be updated to assert the calendar panel instead.

- [ ] **Step 7: Commit**

```bash
git add app/templates/trainer_dashboard.html app/templates/student_dashboard.html \
        app/static/js/dashboard_common.js app/static/js/trainer_dashboard.js \
        app/static/js/student_dashboard.js app/static/css/dashboard.css
git commit -m "feat: replace the deadline list with a deadline calendar"
```

---

### Task 5: Notification history page

**Files:**
- Create: `app/templates/notifications.html`, `app/static/js/notifications.js`, `tests/test_notifications_page.py`
- Modify: `app/dashboards.py`, `app/main.py`, `app/static/js/dashboard_common.js`

**Interfaces:**
- Consumes: the `notifications` table (`id`, `kind`, `title`, `link`, `created_at`, `read_at`).
- Produces: `GET /api/dashboard/notifications?offset=<int>` returning `{"items": [...], "total": int}`, 15 per page.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_notifications_page.py
"""The notification history: every update, oldest reachable, with real times."""

from conftest import register_trainer


def _notify_many(user_id, count):
    from app.db import get_conn, notify
    with get_conn() as conn:
        for n in range(count):
            notify(conn, user_id, "assigned", f"Update {n}", "/trainer")


def test_the_history_pages_fifteen_at_a_time(client):
    register_trainer(client)
    user_id = client.get("/auth/me").json()["id"]
    _notify_many(user_id, 20)

    first = client.get("/api/dashboard/notifications").json()
    assert len(first["items"]) == 15
    assert first["total"] == 20

    second = client.get("/api/dashboard/notifications?offset=15").json()
    assert len(second["items"]) == 5


def test_every_notification_carries_its_timestamp(client):
    register_trainer(client)
    user_id = client.get("/auth/me").json()["id"]
    _notify_many(user_id, 1)
    item = client.get("/api/dashboard/notifications").json()["items"][0]
    assert item["created_at"]
    assert item["title"] == "Update 0"


def test_the_history_page_renders(client):
    register_trainer(client)
    assert client.get("/notifications").status_code == 200


def test_the_history_is_private_to_its_owner(client):
    register_trainer(client)
    owner = client.get("/auth/me").json()["id"]
    _notify_many(owner, 3)
    client.post("/auth/logout")

    from conftest import register
    register(client, email="nosy@example.com")
    assert client.get("/api/dashboard/notifications").json()["items"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_notifications_page.py -v`
Expected: FAIL — 404, the endpoint and page do not exist.

- [ ] **Step 3: Add the endpoint**

In `app/dashboards.py`, beside `mark_notifications_read`:

```python
@router.get("/notifications")
def notification_history(
    offset: int = 0, user: sqlite3.Row = Depends(get_current_user)
) -> dict:
    """Every notification this user has had, newest first.

    Ordered strictly by time, unlike the bell, which floats unread to the top.
    A history that reorders itself as things are read is not a history.
    """
    user_id = int(user["id"])
    with get_conn() as conn:
        items = _rows(
            conn.execute(
                "SELECT id, kind, title, link, created_at, read_at FROM notifications"
                " WHERE user_id = ? ORDER BY created_at DESC, id DESC"
                " LIMIT ? OFFSET ?",
                (user_id, ACTIVITY_PAGE, max(0, offset)),
            )
        )
        total = _scalar(
            conn, "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (user_id,)
        )
    return {"items": items, "total": total}
```

- [ ] **Step 4: Add the page route**

In `app/main.py`, beside the other literal page routes (before any single-segment path parameter):

```python
@app.get("/notifications", include_in_schema=False)
def notifications_page(request: Request, user=Depends(get_optional_user)):
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request,
        "notifications.html",
        {"email": user["email"], "name": display_name(user), "role": user["role"]},
    )
```

- [ ] **Step 5: Add the template**

Create `app/templates/notifications.html`:

```jinja
{% extends "base.html" %}
{% from "_topbar.html" import topbar %}
{% block title %}Notifications · Python Learning Platform{% endblock %}
{% block body_class %}colab dash{% endblock %}
{% block head %}
<link rel="stylesheet" href="/static/css/dashboard.css?v={{ asset_v() }}">
{% endblock %}

{% block content %}
{{ topbar(role, name, back='/' ~ role, heading='Notifications', bell=true) }}

<main class="dash-main narrow">
  <div class="dash-head">
    <div>
      <h1>Notifications</h1>
      <p>Everything you have been sent, newest first.</p>
    </div>
  </div>

  <section class="panel">
    <div class="panel-body">
      <ul class="feed timeline" id="notification-list"></ul>
    </div>
    <div class="pager" id="notification-pager" hidden>
      <button class="cb-btn" id="notification-more">Show older</button>
    </div>
  </section>
</main>

<div class="flash" id="flash" role="status" aria-live="polite" hidden></div>
<div class="toast" id="toast" hidden></div>
{% endblock %}

{% block scripts %}
<script>window.PAGE = { kind: "notifications" };</script>
<script src="/static/js/dashboard_common.js?v={{ asset_v() }}"></script>
<script src="/static/js/notifications.js?v={{ asset_v() }}"></script>
{% endblock %}
```

- [ ] **Step 6: Add the page script**

Create `app/static/js/notifications.js`:

```js
// Notification history. The bell shows "3 minutes ago" because recency is what
// matters there; a history shows the real date and time, because "6 days ago"
// is useless when you are trying to remember which day something arrived.
(function () {
  const D = window.Dash;
  const ICONS = {
    assigned: "📌", approve: "✅", request_changes: "✏️",
    submitted: "📝", reopen: "🔓",
  };
  let offset = 0;

  function stamp(iso) {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      day: "numeric", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  }

  async function load() {
    const data = await D.api(`/api/dashboard/notifications?offset=${offset}`);
    const list = document.getElementById("notification-list");
    if (!offset) list.textContent = "";

    if (!data.items.length && !offset) {
      list.append(D.el("li", {}, D.el("span", { class: "meta" }, "Nothing yet.")));
    }
    data.items.forEach((n) => {
      const li = D.el(
        "li",
        { class: n.read_at ? "" : "unread" },
        D.el("span", {}, `${ICONS[n.kind] || "•"} ${n.title}`),
        D.el("time", { title: n.created_at }, stamp(n.created_at))
      );
      if (n.link) {
        li.style.cursor = "pointer";
        li.addEventListener("click", () => (window.location.href = n.link));
      }
      list.append(li);
    });

    offset += data.items.length;
    document.getElementById("notification-pager").hidden = offset >= data.total;
  }

  document.getElementById("notification-more").addEventListener("click", () =>
    load().catch((e) => D.flash(e.message, "error"))
  );
  load().catch((e) => D.flash(e.message, "error"));
})();
```

- [ ] **Step 7: Point the bell footer at it**

In `app/static/js/dashboard_common.js`, in `renderNotifications`, replace the footer block:

```js
    if (foot) {
      foot.hidden = false;
      foot.textContent = "";
      const link = el("a", { href: "/notifications" }, "See all notifications");
      foot.append(link);
    }
```

- [ ] **Step 8: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_notifications_page.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 9: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add app/templates/notifications.html app/static/js/notifications.js \
        app/dashboards.py app/main.py app/static/js/dashboard_common.js \
        tests/test_notifications_page.py
git commit -m "feat: add a full notification history page"
```

---

### Task 6: Global search

**Files:**
- Create: `app/search.py`, `tests/test_search.py`
- Modify: `app/main.py`, `app/static/js/dashboard_common.js`

**Interfaces:**
- Consumes: `require_trainer` / `get_current_user` from `app/deps.py`.
- Produces: `GET /api/search?q=<str>` returning
  `{"results": [{"kind": "exercise"|"module"|"student", "label": str, "sub": str, "link": str}]}`,
  at most 5 per kind.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_search.py
"""Header search: titles and names, scoped to what the viewer may see."""

from conftest import register, register_trainer
from test_modules import a_course


def test_a_trainer_finds_their_own_module(client):
    register_trainer(client)
    from test_modules import upload
    upload(client, title="Python Loops")
    results = client.get("/api/search?q=loops").json()["results"]
    assert any(r["kind"] == "module" and "Loops" in r["label"] for r in results)


def test_a_trainer_finds_a_student_by_name(client):
    register(client, email="aditi@example.com", name="Aditi Sharma")
    client.post("/auth/logout")
    register_trainer(client)
    results = client.get("/api/search?q=aditi").json()["results"]
    assert any(r["kind"] == "student" for r in results)


def test_a_student_never_finds_an_unassigned_module(client):
    """Authorisation is the point of this endpoint, not a detail of it."""
    register_trainer(client)
    from test_modules import upload
    upload(client, title="Secret Draft")
    client.post("/auth/logout")

    register(client, email="outsider@example.com")
    results = client.get("/api/search?q=secret").json()["results"]
    assert results == []


def test_an_empty_query_returns_nothing_and_does_not_error(client):
    register_trainer(client)
    res = client.get("/api/search?q=")
    assert res.status_code == 200
    assert res.json()["results"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_search.py -v`
Expected: FAIL with 404 — the route does not exist.

- [ ] **Step 3: Write the router**

Create `app/search.py`:

```python
"""Header search across the things a person can name (spec: titles only).

Deliberately not full-text over module content: that is a different problem
with different storage, and a search box that sometimes returns a paragraph
from the middle of a lesson is worse than one that reliably returns titles.

Every query is scoped by role. A student searches only what has been assigned
to them, so this endpoint can never become a way to enumerate drafts.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from .db import get_conn
from .deps import get_current_user
from .names import display_name

router = APIRouter(prefix="/api", tags=["search"])

PER_KIND = 5


@router.get("/search")
def search(q: str = "", user: sqlite3.Row = Depends(get_current_user)) -> dict:
    term = q.strip()
    if not term:
        return {"results": []}
    like = f"%{term}%"
    user_id = int(user["id"])
    is_trainer = user["role"] == "trainer"
    results: list[dict] = []

    with get_conn() as conn:
        if is_trainer:
            for row in conn.execute(
                "SELECT id, title FROM exercises WHERE trainer_id = ? AND title LIKE ?"
                " ORDER BY updated_at DESC LIMIT ?",
                (user_id, like, PER_KIND),
            ):
                results.append({
                    "kind": "exercise", "label": row["title"], "sub": "Exercise",
                    "link": f"/trainer/exercises/{row['id']}",
                })
            for row in conn.execute(
                "SELECT id, title FROM modules WHERE trainer_id = ? AND title LIKE ?"
                " ORDER BY updated_at DESC LIMIT ?",
                (user_id, like, PER_KIND),
            ):
                results.append({
                    "kind": "module", "label": row["title"], "sub": "Module",
                    "link": f"/trainer/modules/{row['id']}",
                })
            for row in conn.execute(
                "SELECT * FROM users WHERE role = 'student'"
                " AND (full_name LIKE ? OR email LIKE ?) LIMIT ?",
                (like, like, PER_KIND),
            ):
                results.append({
                    "kind": "student", "label": display_name(row),
                    "sub": row["email"],
                    "link": f"/trainer/students/{row['id']}",
                })
        else:
            for row in conn.execute(
                "SELECT a.id, e.title FROM assignments a"
                " JOIN exercises e ON e.id = a.exercise_id"
                " WHERE a.student_id = ? AND e.title LIKE ? LIMIT ?",
                (user_id, like, PER_KIND),
            ):
                results.append({
                    "kind": "exercise", "label": row["title"], "sub": "Exercise",
                    "link": f"/student/assignments/{row['id']}/solve",
                })
            for row in conn.execute(
                "SELECT m.id, m.title FROM modules m"
                " JOIN module_assignments ma ON ma.module_id = m.id"
                " WHERE ma.student_id = ? AND m.status = 'published'"
                " AND m.title LIKE ? LIMIT ?",
                (user_id, like, PER_KIND),
            ):
                results.append({
                    "kind": "module", "label": row["title"], "sub": "Module",
                    "link": f"/student/modules/{row['id']}",
                })

    return {"results": results}
```

- [ ] **Step 4: Register the router**

In `app/main.py`, beside the other `include_router` calls:

```python
app.include_router(search.router)
```

and add `search` to the `from . import ...` line at the top.

- [ ] **Step 5: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_search.py -v`
Expected: PASS, 4 tests. (`conftest.register` takes a `name=` keyword — verified — so the student in `test_a_trainer_finds_a_student_by_name` gets a real `full_name` to match against.)

- [ ] **Step 6: Wire the input**

In `app/static/js/dashboard_common.js`, after the bell wiring:

```js
  // Header search. Debounced because it fires per keystroke, and a query per
  // character would put a request in flight for every letter of a word.
  (function wireSearch() {
    const input = document.getElementById("global-search");
    if (!input) return;
    const panel = document.getElementById("search-results");
    let timer = null;

    async function run() {
      const q = input.value.trim();
      if (!q) { panel.hidden = true; return; }
      try {
        const data = await api(`/api/search?q=${encodeURIComponent(q)}`);
        panel.textContent = "";
        if (!data.results.length) {
          panel.append(el("div", { class: "search-empty" }, "Nothing found."));
        }
        data.results.forEach((r) => {
          const row = el(
            "a",
            { class: "search-hit", href: r.link },
            el("span", { class: "hit-label" }, r.label),
            el("span", { class: "hit-sub" }, r.sub)
          );
          panel.append(row);
        });
        panel.hidden = false;
      } catch (err) {
        panel.hidden = true;
      }
    }

    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(run, 220);
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".header-search")) panel.hidden = true;
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") panel.hidden = true;
    });
  })();
```

- [ ] **Step 7: Style the results**

Append to `app/static/css/shell.css`:

```css
.search-hit {
  display: flex; flex-direction: column; gap: 1px;
  padding: 9px 11px; border-radius: 9px;
  color: var(--text); text-decoration: none;
}
.search-hit:hover { background: var(--cell-bg); }
.hit-label { font-size: 13.5px; }
.hit-sub { font-size: 11.5px; color: var(--text-dim); }
.search-empty { padding: 12px; font-size: 13px; color: var(--text-dim); }
```

- [ ] **Step 8: Try it**

Sign in as trainer, type "loop" in the header. Confirm results appear, clicking one navigates, Escape closes it, and that a student signed in sees only their own assigned work.

- [ ] **Step 9: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add app/search.py app/main.py app/static/js/dashboard_common.js \
        app/static/css/shell.css tests/test_search.py
git commit -m "feat: add header search across exercises, modules and students"
```

---

### Task 7: Deadline dropdown on the Exercises pages

**Files:**
- Modify: `app/templates/student_exercises.html:24-29`, `app/templates/trainer_section.html:37-42`, `app/static/js/student_exercises.js`, `app/static/js/trainer_section.js`, `app/static/css/dashboard.css`

**Interfaces:**
- Consumes: the exercise/assignment lists both pages already fetch, each item carrying `due_date` (ISO string or null).
- Produces: a `#deadline-filter` `<select>` on both pages, filtering client-side over data already loaded.

- [ ] **Step 1: Add the control to both templates**

In `app/templates/student_exercises.html`, inside the existing `<div class="filters" id="filters">` block's parent, after the filter buttons:

```jinja
      <select id="deadline-filter" class="deadline-filter" aria-label="Filter by deadline">
        <option value="all">All deadlines</option>
        <option value="overdue">Overdue</option>
        <option value="week">Due in 7 days</option>
        <option value="month">Due in 30 days</option>
        <option value="none">No deadline</option>
      </select>
```

Add the identical block to `app/templates/trainer_section.html` after the From/To date inputs.

- [ ] **Step 2: Add the predicate to both scripts**

In `app/static/js/student_exercises.js`, near the existing filter logic:

```js
  // Windows are from now, not calendar weeks, and they overlap on purpose:
  // something due tomorrow is in both "7 days" and "30 days", because a person
  // filtering for the month expects everything landing in it.
  function matchesDeadline(item, mode) {
    if (mode === "all") return true;
    const raw = item.due_date;
    if (mode === "none") return !raw;
    if (!raw) return false;
    const due = new Date(raw);
    const now = new Date();
    if (mode === "overdue") return due < now;
    const days = (due - now) / 86400000;
    if (mode === "week") return days >= 0 && days <= 7;
    if (mode === "month") return days >= 0 && days <= 30;
    return true;
  }
```

Fold `matchesDeadline(item, deadlineMode)` into the existing predicate that the status buttons already drive, so the two filters compose rather than override each other. Add the same function and wiring to `app/static/js/trainer_section.js`.

- [ ] **Step 3: Wire the control**

In both scripts:

```js
  const deadlineEl = document.getElementById("deadline-filter");
  let deadlineMode = "all";
  if (deadlineEl) {
    deadlineEl.addEventListener("change", () => {
      deadlineMode = deadlineEl.value;
      render();
    });
  }
```

where `render()` is the function each file already uses to repaint its list.

- [ ] **Step 4: Style it**

Append to `app/static/css/dashboard.css`:

```css
.deadline-filter {
  padding: 7px 11px; border-radius: 9px;
  border: 1px solid var(--border);
  background: var(--surface); color: var(--text); font-size: 13px;
}
```

- [ ] **Step 5: Try every option**

On both Exercises pages, step through all five options. Confirm the status buttons and the dropdown **compose** — "To do" plus "Overdue" must show only exercises that are both, not one or the other. Confirm "No deadline" shows exercises whose `due_date` is null.

- [ ] **Step 6: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/templates/student_exercises.html app/templates/trainer_section.html \
        app/static/js/student_exercises.js app/static/js/trainer_section.js \
        app/static/css/dashboard.css
git commit -m "feat: filter exercises by deadline window"
```

---

## Final verification

- [ ] Run the full suite one more time: `.venv\Scripts\python.exe -m pytest -q` — expect PASS with no new warnings.
- [ ] Sign in as **both** roles and visit every page: dashboard, exercises, modules, students (trainer), a module player, a solve page, profile, settings, notifications. Confirm the sidebar renders on all of them and nothing sits underneath it.
- [ ] Check both themes. The tinted stat cards and the calendar's today-highlight are the two places contrast can fail.
- [ ] Narrow the window past 1000px and 700px. Confirm the rail and the off-canvas states.
- [ ] Confirm the browser console is clean on the dashboard, the notification history and one exercises page.

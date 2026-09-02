# Portal Redesign — Phase 1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give both portals one themeable token system, one global navigation bar, and a Settings page where a user can change theme, password and name.

**Architecture:** Unify the two competing CSS token vocabularies onto the root element so they respond to a `data-theme` attribute; set that attribute from `localStorage` in a `<head>` script before first paint and reconcile it against the account via `/auth/me`. Rewrite the single shared `_topbar.html` macro so navigation changes in one file. Add a settings router alongside the existing auth router, following the same `APIRouter` + `Depends(get_current_user)` conventions.

**Tech Stack:** FastAPI, Jinja2, SQLite (via `sqlite3`, no ORM), Pydantic v2, bcrypt, PyJWT, vanilla JavaScript (no build step), pytest + `fastapi.testclient`.

**Spec:** `docs/superpowers/specs/2026-09-02-portal-redesign-design.md`

## Global Constraints

- Python target is whatever `.venv` holds; run everything through `.venv\Scripts\python.exe`, never bare `python`.
- Tests run with `.venv\Scripts\python.exe -m pytest`. `pytest.ini` sets the config; `tests/conftest.py` points the app at a throwaway DB and must not be bypassed.
- No new runtime dependencies. No build step for CSS or JS — the browser loads the files directly.
- Every schema change is additive and idempotent, applied through the existing migration helpers in `app/db.py`. Never `DROP COLUMN`, never rebuild a table.
- Static URLs are cache-busted by `asset_v()`; always reference assets as `/static/...?v={{ asset_v() }}`.
- Page routes live in `app/main.py` and must be declared as **literal** paths before any single-segment path parameter that would swallow them — `main.py` carries a comment explaining the `/trainer/{section}` bug this caused before.
- The three theme values are exactly `system`, `light`, `dark`. `system` resolves to the dark palette unless the OS reports `prefers-color-scheme: light`.
- bcrypt considers at most 72 bytes; passwords are capped at 72 and floored at 8 characters, matching `Credentials` in `app/schemas.py`.
- A display name is never a raw email address. Use the `display_name` helper from Task 1 everywhere a person is shown.
- Commit after every task. Work stays on the `portal-redesign` branch.

---

## File Structure

**Created:**
- `app/names.py` — the single `display_name` helper. Small and dependency-free so templates, routers and tests can all import it.
- `app/settings_routes.py` — `/api/settings` router: theme and profile. Kept out of `auth.py` because it is account preferences, not authentication.
- `app/templates/settings.html` — the Settings page shell.
- `app/static/js/settings.js` — Settings page behaviour.
- `tests/test_settings.py` — covers the theme, profile and password endpoints, and the new page routes.

**Modified:**
- `app/db.py` — add the `theme` column to the users migration.
- `app/deps.py` — select `theme` so it reaches templates and `/auth/me`.
- `app/schemas.py` — `PasswordChangeIn`, `ThemeIn`, `ProfileIn`.
- `app/auth.py` — `POST /auth/password`; add `theme` to `/auth/me`.
- `app/main.py` — register the settings router, add `GET /settings`, use `display_name` for every `name` context value.
- `app/static/css/styles.css` — the unified token sets for all three themes.
- `app/static/css/colab.css` — strip colour tokens off `.colab`, keep layout.
- `app/static/css/dashboard.css` — move `--shadow-card` into the token sets; convert remaining literals.
- `app/templates/base.html` — theme bootstrap script.
- `app/templates/_topbar.html` — the rewritten global bar.
- 18 templates that call `topbar(...)` — pass the new `current` argument.

---

### Task 1: Display-name helper and the theme column

**Files:**
- Create: `app/names.py`
- Modify: `app/db.py` (the `_migrate_user_columns` tuple)
- Modify: `app/deps.py` (the `SELECT` in `_user_from_request`)
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `display_name(row) -> str`, accepting any mapping with `full_name`, `first_name`, `last_name` and `email` keys (a `sqlite3.Row` or a `dict`). Every later task calls it. The `users.theme` column, default `'system'`, becomes readable on the row returned by `get_current_user` / `get_optional_user`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings.py`:

```python
from conftest import register, register_trainer

from app.names import display_name


def test_display_name_prefers_full_name():
    row = {"full_name": "Nishanth Kumar", "first_name": "", "last_name": "", "email": "n@x.com"}
    assert display_name(row) == "Nishanth Kumar"


def test_display_name_falls_back_to_name_parts():
    row = {"full_name": "", "first_name": "Nishanth", "last_name": "Kumar", "email": "n@x.com"}
    assert display_name(row) == "Nishanth Kumar"


def test_display_name_prettifies_the_email_local_part():
    row = {"full_name": "", "first_name": "", "last_name": "", "email": "kuttyxkutty123@gmail.com"}
    assert display_name(row) == "Kuttyxkutty123"


def test_display_name_splits_dots_and_underscores():
    row = {"full_name": "", "first_name": "", "last_name": "", "email": "ranjith.r_iiitk@example.com"}
    assert display_name(row) == "Ranjith R Iiitk"


def test_display_name_never_returns_a_raw_email():
    row = {"full_name": "", "first_name": "", "last_name": "", "email": "someone@example.com"}
    assert "@" not in display_name(row)


def test_new_account_defaults_to_the_system_theme(client):
    register(client)
    assert client.get("/auth/me").json()["theme"] == "system"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_settings.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.names'`.

- [ ] **Step 3: Write the helper**

Create `app/names.py`:

```python
"""How a person is shown in the UI.

A raw email address is never a display name. Most seeded accounts have an
empty `full_name`, so without this fallback the dashboards greet people with
their email address, which is what this replaces.
"""

from __future__ import annotations

from typing import Mapping


def display_name(row: Mapping) -> str:
    """The name to show for one user row, in order of preference."""
    full = (row["full_name"] or "").strip()
    if full:
        return full

    parts = f"{(row['first_name'] or '').strip()} {(row['last_name'] or '').strip()}".strip()
    if parts:
        return parts

    local = (row["email"] or "").split("@")[0]
    words = local.replace(".", " ").replace("_", " ").replace("-", " ").split()
    return " ".join(word.capitalize() for word in words) or "User"
```

- [ ] **Step 4: Add the theme column**

In `app/db.py`, inside `_migrate_user_columns`, add one entry to the tuple of
`(column, ddl)` pairs, after the `is_active` line:

```python
        ("theme", "TEXT NOT NULL DEFAULT 'system'"),
```

In `app/deps.py`, extend the `SELECT` in `_user_from_request` so the column
reaches every caller:

```python
        return conn.execute(
            "SELECT id, email, created_at, role, full_name, first_name, last_name, phone,"
            " is_active, theme"
            " FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
```

In `app/auth.py`, add `theme` to the dict returned by `me`:

```python
        "theme": user["theme"],
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_settings.py -v`

Expected: PASS, 6 passed.

- [ ] **Step 6: Run the whole suite to confirm nothing regressed**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass. The `SELECT` widened by one column, which nothing asserts on.

- [ ] **Step 7: Commit**

```bash
git add app/names.py app/db.py app/deps.py app/auth.py tests/test_settings.py
git commit -m "Add display-name helper and the users.theme column"
```

---

### Task 2: Password change endpoint

**Files:**
- Modify: `app/schemas.py`
- Modify: `app/auth.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `hash_password`, `verify_password`, `set_session_cookie` from `app/security.py`; `get_current_user` from `app/deps.py`.
- Produces: `POST /auth/password` taking `{current_password, new_password, confirm_password}` and returning `{"ok": true}`. Task 6's `settings.js` calls it.

Note for the implementer: `get_current_user` does **not** select `password_hash`, so the route must fetch it. Do not add it to the dependency's `SELECT` — it would then travel into every template context.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings.py`:

```python
def _change_password(client, current="password123", new="newpassword456", confirm=None):
    return client.post(
        "/auth/password",
        json={
            "current_password": current,
            "new_password": new,
            "confirm_password": new if confirm is None else confirm,
        },
    )


def test_password_change_succeeds_and_the_new_password_works(client):
    register(client)
    assert _change_password(client).status_code == 200

    client.cookies.clear()
    login = client.post(
        "/auth/login", json={"email": "user@example.com", "password": "newpassword456"}
    )
    assert login.status_code == 200


def test_password_change_keeps_the_session_alive(client):
    register(client)
    _change_password(client)
    # No re-login: the endpoint reissues the cookie.
    assert client.get("/auth/me").status_code == 200


def test_password_change_rejects_a_wrong_current_password(client):
    register(client)
    response = _change_password(client, current="notmypassword")
    assert response.status_code == 400
    assert "current password" in response.json()["detail"].lower()


def test_password_change_rejects_a_mismatched_confirmation(client):
    register(client)
    response = _change_password(client, new="newpassword456", confirm="different12345")
    assert response.status_code == 400
    assert "match" in response.json()["detail"].lower()


def test_password_change_rejects_a_short_new_password(client):
    register(client)
    assert _change_password(client, new="short").status_code == 422


def test_password_change_rejects_reusing_the_current_password(client):
    register(client)
    response = _change_password(client, new="password123")
    assert response.status_code == 400
    assert "different" in response.json()["detail"].lower()


def test_password_change_requires_a_session(client):
    assert _change_password(client).status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_settings.py -k password -v`

Expected: FAIL with 404 responses — the route does not exist.

- [ ] **Step 3: Add the schema**

In `app/schemas.py`, after `Credentials`:

```python
class PasswordChangeIn(BaseModel):
    """Changing your own password from Settings."""

    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=8, max_length=72)
    confirm_password: str = Field(min_length=8, max_length=72)
```

- [ ] **Step 4: Add the route**

In `app/auth.py`, import the new schema and add the route after `logout`:

```python
@router.post("/password")
def change_password(
    body: PasswordChangeIn,
    response: Response,
    user: sqlite3.Row = Depends(get_current_user),
) -> dict:
    """Change your own password (settings requirement 6, both roles)."""
    if body.new_password != body.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The new passwords do not match.",
        )
    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a password different from your current one.",
        )

    with get_conn() as conn:
        # get_current_user deliberately does not carry the hash around.
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user["id"],)
        ).fetchone()
        # 400, not 401: a wrong password here is a form error, not an expired session.
        if row is None or not verify_password(body.current_password, row["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your current password is not correct.",
            )
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(body.new_password), user["id"]),
        )

    # Keep the user signed in on this device.
    set_session_cookie(response, int(user["id"]))
    return {"ok": True}
```

Update the imports at the top of `app/auth.py`:

```python
from .schemas import Credentials, PasswordChangeIn
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_settings.py -k password -v`

Expected: PASS, 7 passed.

- [ ] **Step 6: Run the whole suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app/schemas.py app/auth.py tests/test_settings.py
git commit -m "Add password change endpoint"
```

---

### Task 3: Theme and profile settings endpoints

**Files:**
- Create: `app/settings_routes.py`
- Modify: `app/schemas.py`
- Modify: `app/main.py` (router registration only)
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `display_name` from Task 1; `get_current_user`.
- Produces: `PATCH /api/settings/theme` returning `{"theme": <value>}`, and `PATCH /api/settings/profile` returning `{"first_name", "last_name", "phone", "full_name", "display_name"}`. Task 6's `settings.js` calls both.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings.py`:

```python
def test_theme_persists_to_the_account(client):
    register(client)
    response = client.patch("/api/settings/theme", json={"theme": "light"})
    assert response.status_code == 200
    assert response.json()["theme"] == "light"
    assert client.get("/auth/me").json()["theme"] == "light"


def test_theme_rejects_an_unknown_value(client):
    register(client)
    assert client.patch("/api/settings/theme", json={"theme": "sepia"}).status_code == 422


def test_theme_requires_a_session(client):
    assert client.patch("/api/settings/theme", json={"theme": "dark"}).status_code == 401


def test_profile_update_recomputes_the_full_name(client):
    register(client)
    response = client.patch(
        "/api/settings/profile",
        json={"first_name": "Nishanth", "last_name": "Kumar", "phone": "9876543210"},
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Nishanth Kumar"
    assert client.get("/auth/me").json()["full_name"] == "Nishanth Kumar"


def test_profile_update_gives_a_named_display_name(client):
    register(client)
    client.patch(
        "/api/settings/profile",
        json={"first_name": "Nishanth", "last_name": "Kumar", "phone": ""},
    )
    assert client.get("/api/settings/profile").json()["display_name"] == "Nishanth Kumar"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_settings.py -k "theme or profile" -v`

Expected: FAIL with 404 — the router is not mounted.

- [ ] **Step 3: Add the schemas**

In `app/schemas.py`, after `PasswordChangeIn`:

```python
class ThemeIn(BaseModel):
    """Appearance preference (settings requirement 6)."""

    theme: Literal["system", "light", "dark"]


class ProfileIn(BaseModel):
    """Your own name and phone, edited from Settings.

    Names exist so the portals can show a person rather than an email
    address; most seeded accounts have none.
    """

    first_name: str = Field(default="", max_length=60)
    last_name: str = Field(default="", max_length=60)
    phone: str = Field(default="", max_length=30)
```

- [ ] **Step 4: Write the router**

Create `app/settings_routes.py`:

```python
"""Account preferences: appearance and personal details.

Separate from `auth.py`, which owns credentials and sessions.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from .db import get_conn
from .deps import get_current_user
from .names import display_name
from .schemas import ProfileIn, ThemeIn

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _profile_payload(row: sqlite3.Row | dict) -> dict:
    return {
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "phone": row["phone"],
        "full_name": row["full_name"],
        "display_name": display_name(row),
        "email": row["email"],
        "theme": row["theme"],
    }


@router.get("/profile")
def read_profile(user: sqlite3.Row = Depends(get_current_user)) -> dict:
    return _profile_payload(user)


@router.patch("/profile")
def update_profile(
    body: ProfileIn, user: sqlite3.Row = Depends(get_current_user)
) -> dict:
    first = body.first_name.strip()
    last = body.last_name.strip()
    full = f"{first} {last}".strip()
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET first_name = ?, last_name = ?, phone = ?, full_name = ?"
            " WHERE id = ?",
            (first, last, body.phone.strip(), full, user["id"]),
        )
        row = conn.execute(
            "SELECT email, full_name, first_name, last_name, phone, theme"
            " FROM users WHERE id = ?",
            (user["id"],),
        ).fetchone()
    return _profile_payload(row)


@router.patch("/theme")
def update_theme(body: ThemeIn, user: sqlite3.Row = Depends(get_current_user)) -> dict:
    with get_conn() as conn:
        conn.execute("UPDATE users SET theme = ? WHERE id = ?", (body.theme, user["id"]))
    return {"theme": body.theme}
```

- [ ] **Step 5: Mount the router**

In `app/main.py`, add `settings_routes` to the package import line and include it
alongside the others:

```python
from . import assignments, auth, dashboards, files, modules, notebooks, settings_routes, ws
```

```python
app.include_router(settings_routes.router)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_settings.py -k "theme or profile" -v`

Expected: PASS, 5 passed.

- [ ] **Step 7: Run the whole suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add app/settings_routes.py app/schemas.py app/main.py tests/test_settings.py
git commit -m "Add theme and profile settings endpoints"
```

---

### Task 4: Unify the CSS tokens and add the three themes

**Files:**
- Modify: `app/static/css/styles.css`
- Modify: `app/static/css/colab.css:1-33`
- Modify: `app/static/css/dashboard.css:6`
- Modify: `app/templates/base.html`

**Interfaces:**
- Consumes: nothing.
- Produces: the canonical token set on `:root`, responding to `data-theme` values `system`, `light` and `dark`. Every later task and phase styles against these names only.

Context the implementer needs: `colab.css` currently defines colour tokens on the
`.colab` body class (lines 9-23) using a **light** palette, while `styles.css`
`:root` defines an overlapping set using a **dark** one. `.colab` is on the body
of every dashboard page and its stylesheet loads second, so light wins there and
dark governs only the login page. Both blocks must collapse into one set on
`:root` before any theme switching can work.

Canonical names, and what merges into them:

| Canonical | Absorbs |
| --- | --- |
| `--bg` | — |
| `--surface` | `--bg-elev`, `--panel` |
| `--cell-bg` | `--bg-inset` |
| `--border` | — |
| `--border-strong` | `--border-soft` |
| `--text`, `--text-dim`, `--text-mute` | — |
| `--blue` | `--accent` |
| `--blue-dark` | `--accent-2` |
| `--green`, `--red`, `--amber` | — |
| `--shadow-card` | moves here from `dashboard.css:6` |
| `--overlay` | new; replaces hardcoded `rgba(0,0,0,.45)` shadows |
| `--mono`, `--sans`, `--radius` | — |

- [ ] **Step 1: Replace the token block in `styles.css`**

`styles.css` begins with a UTF-8 BOM and its comment banners contain mojibake
(`â”€`). Leave both alone — replace only the `:root { ... }` block, from `:root {`
through its closing brace, with:

```css
/* One token set for the whole platform.

   These used to be defined twice with opposite palettes: dark here, and light
   again on `.colab` in colab.css, which every dashboard body carries. Light won
   on the dashboards purely through load order. Both blocks now live here so a
   `data-theme` attribute on <html> can switch them.

   `system` follows the operating system, and stays dark unless the OS asks for
   light -- the "system (default black)" requirement. */

:root,
:root[data-theme="system"],
:root[data-theme="dark"] {
  --bg:            #0e1116;
  --surface:       #151a21;
  --cell-bg:       #0a0d12;
  --border:        #232c38;
  --border-strong: #313d4d;
  --text:          #dfe6f0;
  --text-dim:      #8b97a8;
  --text-mute:     #5d6879;
  --blue:          #4ea3ff;
  --blue-dark:     #7c5cff;
  --green:         #3fb950;
  --red:           #ff6b6b;
  --amber:         #e3b341;
  --shadow-card:   0 1px 3px rgba(0, 0, 0, .5), 0 1px 2px rgba(0, 0, 0, .3);
  --overlay:       rgba(0, 0, 0, .55);
  --radius:        9px;
  --mono: "JetBrains Mono", "Cascadia Code", "Fira Code", Consolas, monospace;
  --sans: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

:root[data-theme="light"] {
  --bg:            #ffffff;
  --surface:       #f8fafc;
  --cell-bg:       #f8fafc;
  --border:        #e2e8f0;
  --border-strong: #cbd5e1;
  --text:          #0f172a;
  --text-dim:      #64748b;
  --text-mute:     #8b97a8;
  --blue:          #2563eb;
  --blue-dark:     #1d4ed8;
  --green:         #15803d;
  --red:           #dc2626;
  --amber:         #d97706;
  --shadow-card:   0 1px 3px rgba(15, 23, 42, .08), 0 1px 2px rgba(15, 23, 42, .04);
  --overlay:       rgba(15, 23, 42, .35);
}

/* Duplicated deliberately: CSS cannot share one block between a plain selector
   and one inside a media query. Keep these values identical to [data-theme="light"]. */
@media (prefers-color-scheme: light) {
  :root[data-theme="system"] {
    --bg:            #ffffff;
    --surface:       #f8fafc;
    --cell-bg:       #f8fafc;
    --border:        #e2e8f0;
    --border-strong: #cbd5e1;
    --text:          #0f172a;
    --text-dim:      #64748b;
    --text-mute:     #8b97a8;
    --blue:          #2563eb;
    --blue-dark:     #1d4ed8;
    --green:         #15803d;
    --red:           #dc2626;
    --amber:         #d97706;
    --shadow-card:   0 1px 3px rgba(15, 23, 42, .08), 0 1px 2px rgba(15, 23, 42, .04);
    --overlay:       rgba(15, 23, 42, .35);
  }
}
```

- [ ] **Step 2: Rename the retired token names throughout `styles.css`**

Only `styles.css` uses the old names (30 references). Apply these replacements
across that file:

```
var(--bg-elev)   ->  var(--surface)
var(--panel)     ->  var(--surface)
var(--bg-inset)  ->  var(--cell-bg)
var(--border-soft) -> var(--border-strong)
var(--accent-2)  ->  var(--blue-dark)
var(--accent)    ->  var(--blue)
```

Order matters: replace `--accent-2` before `--accent`, or the first replacement
corrupts the second.

Then verify none survive:

Run: `grep -n -- '--bg-elev\|--bg-inset\|--panel\|--border-soft\|--accent' app/static/css/styles.css`

Expected: no output.

- [ ] **Step 3: Strip the colour tokens off `.colab`**

In `app/static/css/colab.css`, delete lines 10-23 — the fourteen `--*:`
declarations inside the `.colab` block — leaving the layout properties that
follow. The block becomes:

```css
.colab {
  margin: 0;
  height: auto;
  min-height: 100%;
  background: var(--bg);
  color: var(--text);
  font-family: var(--sans);
  font-size: 14px;
}
```

Replace the hardcoded background on the rule above it:

```css
html:has(body.colab) { background: var(--bg); height: auto; }
```

- [ ] **Step 4: Remove the duplicate `--shadow-card`**

In `app/static/css/dashboard.css`, delete the `--shadow-card:` declaration on
line 6; it now lives in the token sets. Leave the two `box-shadow:
var(--shadow-card)` uses alone.

On line 286, replace the hardcoded white:

```css
.resume.empty-state { background: var(--surface); color: var(--text); box-shadow: var(--shadow-card); border: 1px solid var(--border); }
```

- [ ] **Step 5: Convert the remaining hardcoded colours**

Sweep the three stylesheets for literals that must follow the theme. Find them:

Run: `grep -n '#[0-9a-fA-F]\{3,8\}\|rgba(' app/static/css/*.css`

Apply these rules to each hit:

- `#fff` / `#ffffff` used as **text on a coloured button** — leave it. White on a
  blue or red fill is correct in both themes.
- `#fff` / `#ffffff` used as a **surface or page background** — `var(--surface)`.
- `#f8fafc`, `#f7f8fa`, `#f1f3f5`, `#e8eaed`, `#e6e6e6` — `var(--cell-bg)` for
  fills, `var(--border)` for 1px rules.
- `#0f172a`, `#202124`, `#1e1f22` — `var(--text)`.
- `#9aa0a6`, `#80868b`, `#64748b` — `var(--text-dim)`.
- `#1a73e8`, `#2563eb`, `#1d4ed8` — `var(--blue)`; `#6b4ce6`, `#6c4ed9` —
  `var(--blue-dark)`.
- `#fce8e6`, `#b31412` — the error pill: background
  `color-mix(in srgb, var(--red) 12%, transparent)`, text `var(--red)`.
- `#eef3ff` — `color-mix(in srgb, var(--blue) 10%, transparent)`.
- `rgba(26, 115, 232, X)` and `rgba(78, 163, 255, X)` — these are the accent at
  varying alpha: `color-mix(in srgb, var(--blue) <X*100>%, transparent)`.
- `rgba(15, 23, 42, X)`, `rgba(60, 64, 67, X)`, `rgba(32, 33, 36, X)` inside a
  `box-shadow` — `var(--shadow-card)` if it is a card shadow, otherwise
  `var(--overlay)`.
- `rgba(255, 255, 255, X)` over a coloured fill — leave it.

`color-mix` is supported in every browser this app targets and needs no
fallback.

- [ ] **Step 6: Add the theme bootstrap to `base.html`**

Replace the opening `<html>` tag and add the script **before** the stylesheet
link, so the attribute is set before first paint and no page flashes the wrong
palette:

```html
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Python Learning Platform{% endblock %}</title>
  <script>
    // Before first paint: no flash of the previous palette. The account's own
    // preference arrives later over /auth/me and reconciles this.
    (function () {
      var theme = "system";
      try { theme = localStorage.getItem("theme") || "system"; } catch (e) {}
      document.documentElement.setAttribute("data-theme", theme);
    })();
  </script>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#128013;</text></svg>">
  <link rel="stylesheet" href="/static/css/styles.css?v={{ asset_v() }}">
  {% block head %}{% endblock %}
</head>
```

Note the `data-theme="dark"` that was hardcoded on `<html>` is gone — the script
sets it now.

- [ ] **Step 7: Reconcile the stored theme in `dashboard_common.js`**

At the top of the IIFE in `app/static/js/dashboard_common.js`, add:

```javascript
  // The head script applied whatever this browser remembered. The account is
  // the source of truth across devices, so correct it once on load.
  async function syncTheme() {
    try {
      const me = await fetch("/auth/me").then((r) => (r.ok ? r.json() : null));
      if (!me || !me.theme) return;
      if (localStorage.getItem("theme") !== me.theme) {
        localStorage.setItem("theme", me.theme);
        document.documentElement.setAttribute("data-theme", me.theme);
      }
    } catch (e) {
      /* offline or signed out: keep what the head script applied */
    }
  }
  syncTheme();
```

- [ ] **Step 8: Verify by eye**

Run: `.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000`

Open `http://127.0.0.1:8000`, sign in, and check in DevTools that
`document.documentElement.dataset.theme` is `system` and the dashboard renders
dark. Then run `localStorage.setItem("theme","light")` and reload: the dashboard
renders light, with no white-on-white or black-on-black text anywhere. Check the
login page in both.

- [ ] **Step 9: Run the suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: all pass — no test asserts on CSS.

- [ ] **Step 10: Commit**

```bash
git add app/static/css/ app/templates/base.html app/static/js/dashboard_common.js
git commit -m "Unify the CSS tokens and add system/light/dark themes"
```

---

### Task 5: Rewrite the global top bar

**Files:**
- Modify: `app/templates/_topbar.html`
- Modify: `app/main.py` (use `display_name` for every `name` context value)
- Modify: 18 templates that call `topbar(...)`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `display_name` from Task 1.
- Produces: `topbar(role, name, back=None, heading=None, bell=False, current=None)`. `current` is one of `dashboard`, `exercises`, `modules`, `students`, `activity`, or `None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings.py`:

```python
def test_trainer_nav_carries_every_section(client):
    register_trainer(client)
    html = client.get("/trainer").text
    for label in ("Dashboard", "Modules", "Exercises", "Students", "Activity", "Online session"):
        assert label in html


def test_student_nav_carries_every_section(client):
    register(client)
    html = client.get("/student").text
    for label in ("Dashboard", "Exercises", "Modules", "Activity", "Online session"):
        assert label in html
    # Students is a trainer-only section.
    assert ">Students<" not in html


def test_online_session_is_present_but_not_a_link(client):
    register_trainer(client)
    html = client.get("/trainer").text
    assert 'aria-disabled="true"' in html
    assert 'href="/online-session"' not in html


def test_avatar_menu_offers_settings_and_drops_activity_history(client):
    register_trainer(client)
    html = client.get("/trainer").text
    assert 'href="/settings"' in html
    assert "Activity history" not in html


def test_dashboard_greets_by_name_not_email(client):
    register(client, email="kuttyxkutty123@gmail.com")
    html = client.get("/student").text
    assert "Kuttyxkutty123" in html
    assert "kuttyxkutty123@gmail.com" not in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_settings.py -k "nav or online or avatar or greets" -v`

Expected: FAIL — "Online session" absent, `/settings` absent, "Activity history"
present, and the greeting shows the email.

- [ ] **Step 3: Rewrite the macro signature and nav**

In `app/templates/_topbar.html`, change the macro line to:

```jinja
{% macro topbar(role, name, back=None, heading=None, bell=False, current=None) %}
```

Replace the `<nav class="cb-nav">` block with:

```jinja
  <nav class="cb-nav">
    <a class="cb-link {{ 'active' if current == 'dashboard' }}" href="{{ home }}">Dashboard</a>

    {% if role == 'trainer' %}
      <a class="cb-link {{ 'active' if current == 'modules' }}" href="/trainer/modules">Modules</a>

      {# Requirement 1: New exercise and Drafts live under Exercises, not beside
         the profile avatar and not as dashboard buttons. #}
      <div class="cb-menu-wrap">
        <button class="cb-link cb-menu-btn {{ 'active' if current == 'exercises' }}"
                id="ex-menu" type="button" aria-haspopup="true" aria-expanded="false">
          Exercises <span class="caret">▾</span>
        </button>
        <div class="cb-menu" id="ex-menu-panel" hidden>
          <a class="cb-menu-item" href="/trainer/exercises">All exercises</a>
          <a class="cb-menu-item" href="/trainer/exercises/new">New exercise</a>
          <a class="cb-menu-item" href="/trainer/exercises/drafts">Drafts</a>
        </div>
      </div>

      <a class="cb-link {{ 'active' if current == 'students' }}" href="/trainer/students">Students</a>
    {% else %}
      <a class="cb-link {{ 'active' if current == 'exercises' }}" href="/student/exercises">Exercises</a>
      <a class="cb-link {{ 'active' if current == 'modules' }}" href="/student/modules">Modules</a>
    {% endif %}

    <a class="cb-link {{ 'active' if current == 'activity' }}" href="/activity">Activity</a>

    {# Not built yet; present so the navigation is complete. #}
    <span class="cb-link disabled" aria-disabled="true" title="Coming soon">
      Online session <span class="soon">Soon</span>
    </span>
  </nav>
```

- [ ] **Step 4: Update the avatar panel**

Replace the two `avatar-item` links (leaving the logout button) with:

```jinja
      <a class="avatar-item" href="/profile">My profile</a>
      <a class="avatar-item" href="/settings">Settings</a>
```

The `Activity history` link is removed — Activity is a nav section now.

- [ ] **Step 5: Wire the Exercises dropdown**

Inside the existing `<script>` at the bottom of the macro, after the profile
panel wiring and before the logout handler, add:

```javascript
    const exBtn = document.getElementById("ex-menu");
    const exPanel = document.getElementById("ex-menu-panel");
    if (exBtn && exPanel) {
      exBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const open = exPanel.hidden;
        exPanel.hidden = !open;
        exBtn.setAttribute("aria-expanded", String(open));
      });
      document.addEventListener("click", (e) => {
        if (!exPanel.hidden && !e.target.closest(".cb-menu-wrap")) {
          exPanel.hidden = true;
          exBtn.setAttribute("aria-expanded", "false");
        }
      });
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") exPanel.hidden = true;
      });
    }
```

The guard matters: the student bar has no dropdown, and the script runs there too.

- [ ] **Step 6: Style the new pieces**

Append to `app/static/css/colab.css`:

```css
/* ── global nav: active state, dropdown, disabled item ────────────── */

.cb-link.active {
  color: var(--blue);
  font-weight: 600;
  box-shadow: inset 0 -2px 0 var(--blue);
}
.cb-link.disabled {
  color: var(--text-mute);
  cursor: default;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.cb-link .soon {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .04em;
  text-transform: uppercase;
  padding: 1px 6px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--text-mute) 20%, transparent);
}

.cb-menu-wrap { position: relative; display: inline-block; }
.cb-menu-btn { background: none; border: 0; font: inherit; }
.cb-menu-btn .caret { font-size: 10px; margin-left: 2px; }
.cb-menu {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  min-width: 180px;
  padding: 6px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow-card);
  z-index: 50;
}
.cb-menu-item {
  display: block;
  padding: 8px 10px;
  border-radius: 6px;
  color: var(--text);
  text-decoration: none;
  font-size: 13px;
}
.cb-menu-item:hover { background: var(--cell-bg); }
```

- [ ] **Step 7: Pass `current` at all 18 call sites**

Add the argument to each `topbar(...)` call:

| Template | Add |
| --- | --- |
| `activity.html` | `current='activity'` |
| `exercise_detail.html` | `current='exercises'` |
| `exercise_drafts.html` | `current='exercises'` |
| `exercise_form.html` | `current='exercises'` |
| `modules_student.html` | `current='modules'` |
| `modules_trainer.html` | `current='modules'` |
| `module_player.html` | `current='modules'` |
| `module_review.html` | `current='modules'` |
| `profile.html` | *(none — not a nav section)* |
| `review.html` | `current='exercises'` |
| `student_dashboard.html` | `current='dashboard'` |
| `student_detail.html` | `current='students'` |
| `student_exercises.html` | `current='exercises'` |
| `student_exercise_detail.html` | `current='students'` |
| `student_personal.html` | `current='students'` |
| `trainer_dashboard.html` | `current='dashboard'` |
| `trainer_section.html` | `current='exercises'` |
| `trainer_students.html` | `current='students'` |

Also update the usage comment at the top of `_topbar.html` to show the new
argument.

- [ ] **Step 8: Use real names in `main.py`**

Import the helper:

```python
from .names import display_name
```

Then replace every `user["full_name"] or user["email"]` with
`display_name(user)`. There are nine, at these lines:

| Line | Function |
| --- | --- |
| 81 | `trainer_page` |
| 94 | `student_page` |
| 108 | `trainer_students_page` |
| 140 | `student_exercises_page` |
| 152 | `activity_page` |
| 169 | `notebooks_page` |
| 187 | `notebook_page` |
| 213 | `_trainer_page` |
| 288 | `_student_page` |

Confirm none survive:

Run: `grep -n 'full_name"\] or user\["email"\]' app/main.py`

Expected: no output.

In `profile_page`, the template calls `topbar(user['role'], user['full_name'] or
user['email'], ...)`; pass the resolved name through the context instead by
adding `"name": display_name(user)` to that context dict, then change
`profile.html` line 11 to use `name`:

```jinja
{{ topbar(user['role'], name, back=back, heading='My profile') }}
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_settings.py -v`

Expected: all pass.

- [ ] **Step 10: Run the whole suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: all pass. If a dashboard test asserted on an email greeting, update it
to the display name — that is the intended change, not a regression.

- [ ] **Step 11: Commit**

```bash
git add app/templates/ app/static/css/colab.css app/main.py tests/test_settings.py
git commit -m "Rewrite the top bar as the one global navigation"
```

---

### Task 6: The Settings page

**Files:**
- Create: `app/templates/settings.html`
- Create: `app/static/js/settings.js`
- Modify: `app/main.py` (the `GET /settings` route)
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `PATCH /api/settings/theme` and `PATCH /api/settings/profile` (Task 3), `POST /auth/password` (Task 2), the `topbar` macro (Task 5), the theme tokens (Task 4).
- Produces: the `/settings` page. Phase 3 replaces its inline status messages with the shared `D.flash` helper.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings.py`:

```python
def test_settings_page_renders_for_both_roles(client):
    register_trainer(client)
    assert client.get("/settings").status_code == 200
    client.cookies.clear()

    register(client, email="s@example.com")
    page = client.get("/settings")
    assert page.status_code == 200
    for label in ("Appearance", "System", "Light", "Dark", "Change password", "Your details"):
        assert label in page.text


def test_settings_page_redirects_when_signed_out(client):
    response = client.get("/settings", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_settings.py -k settings_page -v`

Expected: FAIL with 404 — the route does not exist.

- [ ] **Step 3: Add the route**

In `app/main.py`, beside `profile_page`:

```python
@app.get("/settings", include_in_schema=False)
def settings_page(request: Request, user=Depends(get_optional_user)):
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "name": display_name(user),
            "back": home_for(user["role"]),
        },
    )
```

- [ ] **Step 4: Write the template**

Create `app/templates/settings.html`:

```jinja
{% extends "base.html" %}
{% from "_topbar.html" import topbar %}
{% block title %}Settings · Python Learning Platform{% endblock %}
{% block body_class %}colab dash{% endblock %}
{% block head %}
<link rel="stylesheet" href="/static/css/colab.css?v={{ asset_v() }}">
<link rel="stylesheet" href="/static/css/dashboard.css?v={{ asset_v() }}">
{% endblock %}

{% block content %}
{{ topbar(user['role'], name, back=back, heading='Settings') }}

<main class="dash-main narrow">
  <div class="dash-head">
    <div>
      <h1>Settings</h1>
      <p>Appearance, your sign-in password, and the name people see.</p>
    </div>
  </div>

  <section class="panel">
    <header><h2>Appearance</h2></header>
    <div class="panel-body">
      <div class="theme-choices" id="theme-choices">
        <label class="theme-choice">
          <input type="radio" name="theme" value="system">
          <span class="swatch system"></span>
          <strong>System</strong>
          <small>Follows your device. Black unless your system asks for light.</small>
        </label>
        <label class="theme-choice">
          <input type="radio" name="theme" value="light">
          <span class="swatch light"></span>
          <strong>Light</strong>
          <small>Always light.</small>
        </label>
        <label class="theme-choice">
          <input type="radio" name="theme" value="dark">
          <span class="swatch dark"></span>
          <strong>Dark</strong>
          <small>Always dark.</small>
        </label>
      </div>
    </div>
  </section>

  <section class="panel">
    <header><h2>Your details</h2></header>
    <div class="panel-body">
      <div class="field-row">
        <div class="field">
          <label for="first-name">First name</label>
          <input id="first-name" autocomplete="given-name">
        </div>
        <div class="field">
          <label for="last-name">Last name</label>
          <input id="last-name" autocomplete="family-name">
        </div>
      </div>
      <div class="field">
        <label for="phone">Phone</label>
        <input id="phone" autocomplete="tel">
      </div>
      <p class="help">Your email is {{ user['email'] }} and cannot be changed here.</p>
      <div class="row-actions">
        <button class="cb-btn primary" id="save-profile">Save details</button>
      </div>
    </div>
  </section>

  <section class="panel">
    <header><h2>Change password</h2></header>
    <div class="panel-body">
      <div class="field">
        <label for="current-password">Current password</label>
        <input id="current-password" type="password" autocomplete="current-password">
      </div>
      <div class="field-row">
        <div class="field">
          <label for="new-password">New password</label>
          <input id="new-password" type="password" autocomplete="new-password">
        </div>
        <div class="field">
          <label for="confirm-password">Confirm new password</label>
          <input id="confirm-password" type="password" autocomplete="new-password">
        </div>
      </div>
      <p class="help">At least 8 characters.</p>
      <div class="row-actions">
        <button class="cb-btn primary" id="save-password">Change password</button>
      </div>
    </div>
  </section>
</main>

<div class="toast" id="toast" hidden></div>
{% endblock %}

{% block scripts %}
<script src="/static/js/dashboard_common.js?v={{ asset_v() }}"></script>
<script src="/static/js/settings.js?v={{ asset_v() }}"></script>
{% endblock %}
```

- [ ] **Step 5: Write the page script**

Create `app/static/js/settings.js`:

```javascript
// Settings: appearance, personal details, password.
(function () {
  // The shared helpers are published as window.Dash; every page script aliases
  // it to D. dashboard_common.js must load first.
  const D = window.Dash;

  const choices = document.getElementById("theme-choices");
  const root = document.documentElement;

  function currentTheme() {
    try {
      return localStorage.getItem("theme") || "system";
    } catch (e) {
      return "system";
    }
  }

  function selectTheme(value) {
    const input = choices.querySelector(`input[value="${value}"]`);
    if (input) input.checked = true;
  }

  selectTheme(currentTheme());

  choices.addEventListener("change", async (event) => {
    const value = event.target.value;
    // Apply first: the preference is this browser's even if the save fails.
    root.setAttribute("data-theme", value);
    try {
      localStorage.setItem("theme", value);
    } catch (e) {}
    try {
      await D.api("/api/settings/theme", {
        method: "PATCH",
        body: JSON.stringify({ theme: value }),
      });
      D.toast("Theme saved");
    } catch (err) {
      D.toast(`Saved on this device only: ${err.message}`, true);
    }
  });

  const first = document.getElementById("first-name");
  const last = document.getElementById("last-name");
  const phone = document.getElementById("phone");

  D.api("/api/settings/profile")
    .then((me) => {
      first.value = me.first_name || "";
      last.value = me.last_name || "";
      phone.value = me.phone || "";
      selectTheme(me.theme || "system");
    })
    .catch(() => {});

  document.getElementById("save-profile").addEventListener("click", async () => {
    try {
      const saved = await D.api("/api/settings/profile", {
        method: "PATCH",
        body: JSON.stringify({
          first_name: first.value,
          last_name: last.value,
          phone: phone.value,
        }),
      });
      D.toast(`Saved — you appear as ${saved.display_name}`);
    } catch (err) {
      D.toast(err.message, true);
    }
  });

  const current = document.getElementById("current-password");
  const next = document.getElementById("new-password");
  const confirm = document.getElementById("confirm-password");

  document.getElementById("save-password").addEventListener("click", async () => {
    if (next.value !== confirm.value) return D.toast("The new passwords do not match.", true);
    if (next.value.length < 8) return D.toast("Use at least 8 characters.", true);
    try {
      await D.api("/auth/password", {
        method: "POST",
        body: JSON.stringify({
          current_password: current.value,
          new_password: next.value,
          confirm_password: confirm.value,
        }),
      });
      current.value = next.value = confirm.value = "";
      D.toast("Password changed");
    } catch (err) {
      D.toast(err.message, true);
    }
  });
})();
```

- [ ] **Step 6: Style the theme picker**

Append to `app/static/css/dashboard.css`:

```css
/* ── settings: theme picker ───────────────────────────────────────── */

.theme-choices { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.theme-choice {
  display: grid;
  grid-template-columns: auto 1fr;
  grid-template-areas: "radio swatch" "name name" "help help";
  gap: 4px 10px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  cursor: pointer;
}
.theme-choice:has(input:checked) {
  border-color: var(--blue);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--blue) 18%, transparent);
}
.theme-choice input { grid-area: radio; margin: 0; }
.theme-choice .swatch {
  grid-area: swatch;
  height: 34px;
  border-radius: 6px;
  border: 1px solid var(--border);
}
.theme-choice .swatch.system { background: linear-gradient(135deg, #0e1116 50%, #ffffff 50%); }
.theme-choice .swatch.light  { background: #ffffff; }
.theme-choice .swatch.dark   { background: #0e1116; }
.theme-choice strong { grid-area: name; }
.theme-choice small  { grid-area: help; color: var(--text-dim); }

@media (max-width: 760px) {
  .theme-choices { grid-template-columns: 1fr; }
}
```

The three swatches keep literal hex values on purpose: they are previews of the
palettes, so they must not follow the active theme.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_settings.py -v`

Expected: all pass.

- [ ] **Step 8: Verify by hand**

Start the server, sign in, open Settings from the avatar menu. Check each in turn:
switching theme repaints immediately and survives a reload; saving details makes
the greeting on the dashboard change; changing the password succeeds, and the
old password then fails at `/login` while the current session stays alive.

- [ ] **Step 9: Run the whole suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add app/templates/settings.html app/static/js/settings.js app/static/css/dashboard.css app/main.py tests/test_settings.py
git commit -m "Add the Settings page: theme, details and password"
```

---

## Phase 1 exit criteria

- Every page carries the same navigation, and the active section is marked.
- `Online session` appears in both bars, disabled.
- The avatar menu offers My profile, Settings and Log out — no Activity history.
- `/settings` changes theme, name and password, and each takes effect.
- Choosing a theme on one browser and signing in from another carries it across.
- No page greets anyone by email address.
- `.venv\Scripts\python.exe -m pytest -q` is green.

Phase 2 begins from here: dashboards reduced to cards, the drill-down pages, and
the exercise form changes.

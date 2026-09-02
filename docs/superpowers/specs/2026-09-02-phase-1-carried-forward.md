# Phase 1 outcome and findings carried into Phase 2

Date: 2026-09-02
Branch: `portal-redesign`, commits `9d4d84f`..`856ff41`
Spec: `2026-09-02-portal-redesign-design.md`
Plan: `../plans/2026-09-02-portal-redesign-phase-1.md`

Phase 1 delivered the unified token set and three themes, the global navigation,
and the Settings page. Tests went from 115 to 143, all passing.

This file records what Phase 1 did **not** close, so none of it is lost. Each
item says who found it and why it was deferred rather than fixed.

## Must be decided before or during Phase 2

### F1 — The theme is never rendered server-side

The spec's Layer 1 says `base.html` "renders the user's stored theme
server-side". It does not: the bootstrap script reads `localStorage` only, and
the account's theme is reconciled afterwards by `syncTheme()` in
`dashboard_common.js`.

Two consequences:

- On a new browser the first paint is always `system` (dark), then flips once
  `/auth/me` returns — the exact flash the bootstrap exists to prevent.
- **9 of 24 templates never load `dashboard_common.js`** — `activity.html`,
  `student_exercises.html`, `trainer_section.html`, `trainer_students.html`,
  `profile.html`, `notebook.html`, `notebooks.html`, `login.html`. Four are
  first-class nav destinations, so a bookmark straight to `/activity` or
  `/trainer/students` never picks up the account theme at all.

Deferred because it is an architectural change, not a one-line fix. Fixing it
retires F1, and the two theme-reconciliation defects below, together. Every page
Phase 2 adds must otherwise remember to load `dashboard_common.js` or silently
lose theme sync.

Suggested shape: a Jinja context processor (or a non-httponly `theme` cookie set
alongside the session) that emits `data-theme` on `<html>` before any script runs.

### F2 — Changing a password does not invalidate other sessions

`POST /auth/password` rehashes and reissues the cookie for the current device.
The JWT in `app/security.py` carries only `sub`/`iat`/`exp` — no `jti`, and
`app/deps.py` has no revocation check — so every cookie issued before the change
stays valid for the full `SESSION_DAYS`.

For the feature whose usual motive is "someone else may have my password", that
is a real gap. Additive fix consistent with the project's migration pattern: a
`sessions_valid_from` column stamped on password change, compared against the
token's `iat` in `_user_from_request`.

### F3 — Only the signed-in user gets a display name

Phase 1 routed the signed-in user's name through `display_name` everywhere: the
nine `main.py` contexts, both `dashboards.py` user blobs, and the six
`assignments.py` notification strings. No `full_name ... or user["email"]`
pattern survives in `app/`.

But the SQL returning *other* people was not touched, and the JS still falls back
to a raw email:

| Source | Consumer |
| --- | --- |
| `dashboards.py:166` `u.full_name AS name` | `trainer_students.js:15` `s.name \|\| s.email` |
| `dashboards.py:121,135,199` | `trainer_section.js:1`, `trainer_dashboard.js:197` |
| `assignments.py:176,646,657` | `trainer_detail.js:61,114,141,225,241` |
| `modules.py:267` | `modules.js:147` |

The spec says the helper is used by "every API response that returns a person",
so this is short of it. It is legitimately Phase 2 work — the roster and student
detail are Phase 2 deliverables — but note Phase 1 made `/trainer/students` a
top-level nav item, so the "never a raw email" promise is visibly broken on a
page the new navigation now advertises.

### F4 — Stored-XSS sink still needs escaping at the render site

`trainer_section.js:1` interpolates `s.full_name || s.email`, `x.title` and
`x.problem_statement` directly into `innerHTML`; `student_exercises.js:1` does
the same with `a.title` and `a.preview`.

Phase 1 closed the *write* path it had opened — `ProfileIn` now rejects `<` and
`>` in names — but the sink itself is untouched, and exercise titles and problem
statements still reach it unescaped from trainer input.

**Fix this before Phase 2 lands**, because Phase 2 routes more names through that
exact file. The `el()` helper in `dashboard_common.js` is already
`textContent`-based and is the right tool.

## Cosmetic, safe to ship, worth folding into related work

- **F5** — `notebook.html` and `notebooks.html` hand-roll their own top bars and
  never called the shared macro, so they lack the new nav entirely. `/notebooks`
  was an orphan with no way out; Phase 1 fixed only that by making its brand a
  link. Phase 3 reworks the notebook surface anyway.
- **F6** — `/trainer/queue` renders through `trainer_section.html`, which
  hardcodes `current='exercises'`, so it highlights the wrong nav section. Phase 2
  generalises that template to five sections; `current` must become a per-section
  argument then, or all five will highlight Exercises.
- **F7** — `trainer_dashboard.html` still carries `+ New exercise` and `Drafts`
  buttons. The spec removes them once the Exercises dropdown exists; the Phase 1
  plan omitted the step. Self-resolving when Phase 2 rebuilds that header.
- **F8** — Both Escape handlers in `_topbar.html` hide their panel without
  resetting `aria-expanded`. Fix the pair together.
- **F9** — `.colab .toast`'s border is `rgba(255,255,255,.12)` on a light
  `var(--text)` fill, so it is invisible in dark. Phase 3's `D.toast` → `D.flash`
  rewrite replaces that rule.
- **F10** — `--overlay` in light mode is heavier than the shadows it replaced, so
  dropdowns read darker than before. Taste call; check it alongside F11.
- **F11** — `.cb-nav` uses `gap: 2px` and `.cb-link` carries no padding. The bar
  went from four items to six plus a chip, and the new active underline has no
  breathing room. Never seen in a browser — worth one look.
- **F12** — On Settings, `settings.js`'s profile fetch updates only the theme
  radio while `syncTheme()` updates only the `data-theme` attribute. They converge
  normally, but if `/auth/me` fails while `/api/settings/profile` succeeds the
  radio shows one theme while the page renders another — and clicking the shown
  theme fires no `change` event, so the user cannot recover without selecting a
  different theme first. The F1 fix removes this.

## Not verified

**No one has looked at either theme in a browser.** Chrome could not reach the
dev server during Phase 1 (the extension has no site permission for
`localhost:8000`), so colour, contrast and layout were reasoned about but never
seen. A server-side smoke test confirmed all 18 role/page combinations return 200
and carry the new navigation, and every token pair was checked by hand — but that
is not the same as looking. F10 and F11 in particular need eyes.

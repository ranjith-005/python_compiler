# Trainer & student portal redesign

Date: 2026-09-02
Status: approved, not yet implemented
Branch: `portal-redesign`

## Why

The two portals grew feature by feature. Navigation ended up split between a
half-populated top bar and the avatar dropdown; both dashboards became long
scrolling lists that repeat what their own detail pages already show; and a
student solves a coding exercise inside a full Colab notebook, which is a poor
fit for a graded, single-answer problem.

This redesign makes navigation global, reduces each dashboard to a set of
clickable summary cards, gives every card a real page, and replaces the
notebook solve surface with a conventional editor page.

## Scope

In scope: navigation, both dashboards, the card drill-down pages, the student
roster and student detail, the new-exercise form, settings (theme, password,
name), the exercise solve page, and the success-message pattern.

Out of scope: the Online session feature (nav entry only, no implementation),
the module authoring pipeline, the kernel, and the notebook editor itself,
which continues to serve modules and free practice.

## Decisions taken before writing this

Three points were ambiguous in the requirements and were settled with the
requester:

1. The notebook solve surface is replaced by a single-editor page. Notebooks
   remain for modules and free practice.
2. Requirements 3 and 5 for the trainer dashboard conflict. Requirement 5
   wins: the trainer dashboard shows cards only. Upcoming deadlines stay on the
   student dashboard, where student requirement 5 explicitly keeps them.
3. Delivery is phased, with a review point after each phase.

Two further calls were made and accepted:

4. Student requirement 5 restricts the student dashboard to cards and
   deadlines, which evicts the "From your trainer" queries panel. Rather than
   delete it, it moves to the sidebar of `/student/exercises`, so a trainer's
   warning stays reachable.
5. Showing student names instead of email addresses requires names to exist;
   most seeded accounts have an empty `full_name`. Settings therefore gains a
   profile section for first and last name, and any name still blank falls back
   to a prettified email local-part, never the raw address.

## Architecture

Three layers change, in dependency order.

### Layer 1 - design tokens and theme

`app/static/css/styles.css` already defines a `:root` token block, and the three
stylesheets use CSS variables for roughly 90% of their colour values (287
variable references against 74 hardcoded hex literals). Light mode is therefore
a second token block plus the conversion of those 74 literals.

Token sets:

    :root, :root[data-theme="dark"]  { /* dark palette (current values) */ }
    :root[data-theme="light"]        { /* light palette */ }
    @media (prefers-color-scheme: light) {
      :root[data-theme="system"]     { /* light palette */ }
    }

`system` resolves to light only when the operating system actively reports a
light preference; with no preference expressed it stays dark. This matches the
requirement's "system (default black)".

`base.html` currently hardcodes `data-theme="dark"`. It instead renders the
user's stored theme server-side, and carries a small inline script in `<head>`
that reconciles `localStorage` before first paint so a theme change does not
flash the previous palette.

### Layer 2 - navigation

`app/templates/_topbar.html` is already the single shared macro every page
imports, so the global bar is one file to change.

Trainer nav: Dashboard, Modules, Exercises (dropdown), Students, Activity,
Online session.

Student nav: Dashboard, Exercises, Modules, Activity, Online session.

The trainer's Exercises entry is a dropdown holding All exercises, New exercise
and Drafts. The student's is a plain link to `/student/exercises`.

`Online session` renders as a disabled item with a "Soon" chip. It is not a
link and carries `aria-disabled="true"`.

The macro gains a `current` argument so the active page is highlighted; every
call site passes it.

The avatar dropdown becomes My profile, Settings, Log out. "Activity history"
is removed, because Activity is now a top-level nav item.

The trainer dashboard's `+ New exercise` and `Drafts` buttons are removed; both
live in the Exercises dropdown.

### Layer 3 - pages

Each dashboard reduces to summary cards. The panels they lose become pages
reachable by clicking the corresponding card.

## Data model

Four changes, all additive, applied through the existing idempotent migration
pattern in `app/db.py`.

| Change | Table | Purpose |
| --- | --- | --- |
| `theme TEXT NOT NULL DEFAULT 'system'` | `users` | Theme follows the account across browsers |
| `solution_code TEXT NOT NULL DEFAULT ''` | `assignments` | Code store for the single-editor solve page |
| `last_stdin TEXT NOT NULL DEFAULT ''` | `assignments` | Remembers custom run input between visits |
| one-time backfill | `assignments` | Stitches existing notebook code into `solution_code` |

`_migrate_user_columns` already exists and gains the `theme` entry. A new
`_migrate_platform_columns` follows the same shape for the `assignments`
columns, since the platform schema has no migration helper today.

The backfill is guarded by a `migrations` key (`notebook_code_to_solution_v1`)
so it runs once. It reuses the existing `_notebook_code` logic to concatenate
each assignment's code cells. Assignments with no notebook are skipped.

`exercises.input_format`, `exercises.output_format` and `exercises.constraints`
are retained. The form stops writing them and the UI stops rendering them, but
existing rows keep their data and no table rebuild is required.

`assignments.notebook_id` is retained. It is no longer populated for new
assignments, and remains only so historical rows resolve.

## Components

### Settings - `/settings`

One page shared by both roles, three sections.

**Appearance.** Three radio options: System, Light, Dark. Selecting one applies
it immediately via `data-theme` on the root element, writes `localStorage`, and
persists to the account with `PATCH /api/settings/theme`. A failed persist still
leaves the local change applied and shows an error flash.

**Password.** Current password, new password, confirm new password.
`POST /auth/password` verifies the current password with bcrypt, rejects a new
password shorter than 8 characters or longer than 72 bytes (the bcrypt limit
already documented in `security.py`), and rejects a mismatched confirmation. On
success it rehashes and reissues the session cookie so the user is not signed
out. Failure modes return 400 with a specific message; a wrong current password
returns 400, not 401, so it is not confused with an expired session.

**Profile.** First name, last name, phone. `PATCH /api/settings/profile` updates
the columns and recomputes `full_name`.

### Display names

A single helper resolves how a person is shown, used by every template and every
API response that returns a person:

1. `full_name` when set
2. otherwise `first_name last_name` when either is set
3. otherwise the email local-part, underscores and dots replaced by spaces and
   each word capitalised

The raw email is never used as a display name. It remains visible on the profile
page and the student detail page as an explicit "Email" field.

### Trainer dashboard - `/trainer`

Heading, then five cards, then nothing.

| Card | Links to |
| --- | --- |
| Students | `/trainer/students` |
| Pending submissions | `/trainer/pending` |
| Awaiting review | `/trainer/queue` |
| Exercises | `/trainer/exercises` |
| Completed | `/trainer/completed` |

Cards are anchors, not click-handled divs, so keyboard focus, Enter and
middle-click all behave. Each shows its count, label and a one-line description.

Removed from this page: Submissions awaiting review, Pending submissions, Coding
exercises, and Upcoming deadlines.

### Trainer drill-down pages

`/trainer/queue`, `/trainer/exercises` and `/trainer/students` already exist.
`/trainer/pending` and `/trainer/completed` are new.

`trainer_section.html` generalises to render any of them from a `section`
argument supplying heading, description, column set, and whether date filters
apply. The date filters currently on the dashboard panels move here.

### Trainer roster - `/trainer/students`

Rows show the display name, not the email address, and carry no progress bar.
Each row links to `/trainer/students/{id}`.

### Trainer student detail - `/trainer/students/{id}`

Replaces the progress bar with figures:

- assigned, completed, pending, awaiting review
- late submissions, defined as submissions whose `submitted_at` is later than
  the assignment's `due_date`
- on-time rate over submitted work
- average tests passed, as passed over total across submissions
- last active, from `last_opened_at`
- a per-exercise list showing status, due date, submitted date, and whether each
  was late

Late-submission arithmetic is computed in `assignments.student_detail` alongside
the existing aggregation, not in the template.

### New exercise - `/trainer/exercises/new`

Removed: Input format, Output format, Constraints, and the "View drafts" button.

Retained: Title, Problem statement, Sample input, Sample output, Explanation,
Starter code, Due date, Status, Test cases.

The "Assign to" section is renamed **Assign** and lists students by display
name. The submitted payload continues to carry student ids.

### Student dashboard - `/student`

Heading, five cards in a single horizontal row, and Upcoming deadlines. Nothing
else.

The five cards are Assigned, In progress, Awaiting review, Changes requested and
Completed. They sit in one row via `grid-template-columns: repeat(5, 1fr)`,
collapsing to three and then two columns at narrower widths rather than wrapping
unevenly, which is the defect visible in the reference screenshots.

Each card links to `/student/exercises?filter=...`. The card set and the
filter set do not currently match, so the exercises page gains two tabs and the
mapping is fixed as:

| Card | Filter key | Matches assignment status |
| --- | --- | --- |
| Assigned | `all` | every assignment |
| In progress | `in_progress` (new tab) | `in_progress` |
| Awaiting review | `submitted` | `submitted` |
| Changes requested | `changes_requested` | `changes_requested` |
| Completed | `completed` | `approved`, `completed` |

The existing "To do" tab (`open`) is retained alongside them, covering
`assigned`, `in_progress` and `changes_requested` together.

Upcoming deadlines lists open assignments that have a due date, soonest first,
marking overdue ones.

Removed from this page: the Assigned exercises panel, the "From your trainer"
panel, and the resume banner. The exercises panel already exists in full at
`/student/exercises`; the queries panel moves to that page's sidebar.

### Student exercises - `/student/exercises`

Receives the assignments list, its search box and its status filters from the
dashboard, and gains the "From your trainer" queries sidebar. Honours a `filter`
query parameter so the dashboard cards land on the right tab.

### Student modules - `/student/modules`

Each module card gains a progress bar, driven by the existing `module_progress`
table: blocks with `ran_ok = 1` over total code blocks.

### Exercise solve page - `/student/assignments/{id}/solve`

Replaces the notebook as the place a student answers an exercise.

Layout, top to bottom:

- header with back link, exercise title, due date and status
- problem panel: statement, sample input, sample output, explanation
- a two-column work area: code editor on the left, and on the right a stdin box
  above an output pane
- action bar: Run and Submit

`POST /api/assignments/{id}/run` executes the code against the supplied stdin
and returns stdout, stderr and duration. It does not record a submission.
`POST /api/assignments/{id}/submit` takes the current editor contents, saves
them to `solution_code`, and reuses the existing `_evaluate` path against the
exercise's test cases.

Code is autosaved to `solution_code` on a debounce and on page hide, so a
refresh does not lose work.

`_exercise_cells` and the notebook creation in `open_assignment` are retired.
`_notebook_code` is retained only for the one-time backfill.

The same trust boundary as the existing kernel applies: this runs the student's
own code as a normal process. The README's security note covers it and is
unchanged by this work.

### Success messages

`D.toast` is replaced by `D.flash(message, kind)`, where kind is `success`,
`error` or `info`.

A flash renders into a fixed, horizontally centred region near the top of the
content area. It is not modal, does not trap focus, and does not block
interaction. It carries `role="status"` (`role="alert"` for errors) so screen
readers announce it, and it auto-dismisses after roughly three seconds while
staying dismissable by click.

Call sites to convert, with their messages: exercise created, exercise assigned,
draft saved, submission submitted, submission reviewed, query raised, query
replied, password changed, profile saved, theme saved.

## Data flow

Unchanged in shape: page routes in `main.py` render a Jinja shell, and the
page's JavaScript fetches from `/api/...` and renders into it. New endpoints
follow the existing `APIRouter` and `require_trainer` / `require_student`
conventions.

New endpoints:

| Method | Path | Guard |
| --- | --- | --- |
| `POST` | `/auth/password` | authenticated |
| `PATCH` | `/api/settings/theme` | authenticated |
| `PATCH` | `/api/settings/profile` | authenticated |
| `POST` | `/api/assignments/{id}/run` | student |

`POST /api/assignments/{id}/submit` already exists and changes its code source
from notebook cells to `solution_code`.

New page routes, all literal so they cannot be swallowed by an existing
single-segment path parameter, which `main.py` already warns about:

- `/settings`
- `/trainer/pending`
- `/trainer/completed`
- `/student/assignments/{id}/solve`

## Error handling

- Every new API endpoint returns a specific 400 message on validation failure;
  the page surfaces it through an error flash rather than failing silently.
- A wrong current password returns 400, keeping it distinct from the 401 that
  means the session expired.
- Theme persistence failure is non-blocking: the local change stands.
- `/student/assignments/{id}/solve` redirects to `/student` when the assignment
  does not belong to the requesting student, matching how the existing notebook
  route handles a foreign notebook id.
- Run and Submit report a timeout as a normal result, not an exception, reusing
  the existing `CELL_TIMEOUT_SEC` handling.

## Testing

The existing suite must stay green. The material risk is that `submit` stops
reading from notebook cells, which `tests/test_dashboards.py` and
`tests/test_trainer_detail.py` both exercise; those tests are updated to seed
`solution_code` instead.

New coverage:

- password change: success, wrong current password, too short, mismatched
  confirmation, and that the session survives a successful change
- theme: persists to the account and is returned on the next page load
- route guards: each new page returns 200 for the right role and redirects the
  wrong one
- late submissions: an assignment submitted after its due date counts as late,
  one submitted before does not, and one with no due date never does
- solve page: run returns stdout without recording a submission; submit stores
  the code and evaluates it against the test cases
- display names: a user with no `full_name` renders a prettified local-part,
  never the raw email

## Delivery

Three phases, each ending at a working, reviewable state.

**Phase 1 - foundation.** Token sets and light palette, hardcoded-hex cleanup,
`base.html` theme bootstrap, the rewritten top bar, and the Settings page with
its three sections and endpoints.

**Phase 2 - dashboards and pages.** Both dashboards reduced to cards, the two
new trainer pages plus the generalised section template, roster and student
detail by name with late-submission figures, the exercise form changes, and the
student exercises page absorbing the assignments list and queries sidebar.

**Phase 3 - solve page and polish.** The solve page with run, submit and
autosave, the migration and backfill, retirement of the notebook solve path, the
flash-message conversion across all call sites, and module progress bars.

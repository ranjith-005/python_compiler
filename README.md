# Python Learning Platform

A Python assignment and learning platform for a trainer and their students. Trainers
write coding exercises with public and hidden test cases, turn their PDF/PPT/PPTX slides
into learning modules, and review submissions; students solve exercises in a Monaco
(VS Code) editor, run their code in the browser, and work through modules.

FastAPI + SQLite on the back end, server-rendered Jinja pages with plain JavaScript on
the front end. Each Run or Submit executes the student's code in a fresh, short-lived
Python process.

---

## Trainers and students

An account is either a **trainer** or a **student**, and each role signs in to its own
dashboard.

### Trainer dashboard — `/trainer`

Five cards — total students, pending submissions, submissions awaiting review, coding
exercises (published vs draft), completed work — each one opening the page behind it.
Under them, **Recent activity** ten entries at a time with a Next button, beside
**Upcoming sessions** (a placeholder until online sessions are built).

**Students** — `/trainer/students` — is the roster: who, their email, a progress bar, and
whether they are online now. Open a student for their eight figures and every exercise you
gave them; the five actionable cards (assigned, completed, pending, awaiting review, late)
filter that list, while on-time rate, average tests passed and last active are figures only.
**Personal information** holds the account details.

**Exercises** — `/trainer/exercises` — lists everything you have written, with **New
exercise** and **Drafts** as buttons above it. New exercise takes a title, problem statement,
input/output format, samples, constraints and due date, draft or published, with any number
of test cases (each one public or hidden), and assigns it to the students you pick. They are
notified immediately.

**Review** opens a submission: the student's code, its verdict, how many test cases passed,
and a comment box. Approve it, or request modifications and it reopens on the student's side.

### Student dashboard — `/student`

Four cards — assigned, in progress, awaiting review, completed — each one opening the
exercises page filtered to it. Under them, **Upcoming deadlines** beside **Upcoming
sessions**, and **Recent activity** ten entries at a time with a Next button. The bell
carries the five newest notifications, unread first.

`/student/exercises` is the full list: status, due date (overdue in red), last verdict, test
tally, trainer feedback and any query your trainer raised, all on the exercise it belongs to.

**Start** opens the exercise in a Monaco editor — problem statement above, your solution on
the left, stdin and output on the right. **Run** executes what you have written and shows
its output; **Submit** runs it against every test case, hidden ones included, and records the
verdict (Accepted, Wrong Answer, Runtime Error, Syntax Error). A hidden test stays hidden
while it passes; one that fails is shown in full, because "a hidden test failed" on its own
gives you nothing to fix. Once every test passes, Submit files the work and returns you to
your exercise list; once the trainer approves it, the editor is closed for good.

### Learning modules — `/trainer/modules`, `/student/modules`

A trainer uploads the **learning material itself — a PDF, PPT or PPTX**. All
three are read on the server with no Office or LibreOffice installed: `pypdf`
for PDF, `python-pptx` for PPTX, and a small record-walker over the OLE
compound file for the PowerPoint 97-2003 binary `.ppt`. The whole document is
read (there is no page or slide ceiling) and grouped into
ordered learning sections: related slides become one topic, the document's own
order is kept, and practical topics get **code practice** alongside their
content. Nothing is assembled item by item in the website.

Processing runs on a worker and the page reports the stage it has actually
reached — *extracting content → identifying topics → creating sections* — so a
200-page upload never looks frozen.

What comes out is a **draft**. The trainer reviews every section and can rename
it, rewrite its content, add, delete, reorder, merge or split sections, and turn
code practice on or off with its question and starter code. Only **Publish**
makes it visible to students, and sections live in two revisions so a
half-finished edit to a published module cannot reach a student mid-lesson.

The student player renders exactly the published sections, in order. Content is
never conditional on code: a section with no practice still shows everything the
trainer wrote. Each code-practice section carries **its own editor, its own Run
button and its own output** — there is no global Run, and one section's run
cannot touch another's state.

Progress is the student's own record: a section counts when they press **Mark as
complete**, never merely by opening it and never by running its code. The bar is
`completed ÷ total × 100`, computed from the module's real section count, kept
per student and per module, and it survives logout, re-login and the trainer
re-publishing. Completed sections stay open and readable. Trainers see the same
number per student on the module page.

Each run is a fresh, isolated subprocess with a short timeout, so one
learner's runaway `while True` cannot affect anything else.

### Demo data

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.seed          # or, under Docker:
docker compose exec --user app -w /srv/backend web python -m app.seed
```

Creates a trainer, four students, four exercises and a spread of assignments, submissions and
feedback, so both dashboards open with real content. `--reset` recreates it.

| Role | Email | Password |
|---|---|---|
| Trainer | `trainer@pycompiler.dev` | `trainer1234` |
| Student | `aditi@pycompiler.dev` (and `rahul@`, `meera@`, `karthik@`) | `student1234` |

---

## Feature list

- **Two portals** — trainers and students sign in to their own role-scoped dashboard
- **Exercise authoring** — statement, formats, samples, constraints, due date, draft/published
- **Public and hidden test cases** — a hidden case counts towards the verdict and is
  revealed only when it fails
- **Automatic evaluation** on submit: Accepted, Wrong Answer, Runtime Error, Syntax Error
- **Review loop** — approve or request modifications, with comments the student sees inline
- **Learning modules** from uploaded PDF/PPT/PPTX, with per-section code practice and progress
- **Progress tracking and notifications** for both roles, plus per-user activity feeds

---

## Run it with Docker

```bash
cp .env.example .env        # optional: set SECRET_KEY, GROQ_API_KEY
docker compose up --build
```

Open <http://127.0.0.1:8000>. The database, student workspaces and uploaded module files
live in the `pycompiler-data` Docker volume, so they survive rebuilds.
`docker compose down` stops it; `docker compose down -v` also **deletes that data**.

The port is bound to `127.0.0.1` only. Publish it through a reverse proxy or a
Cloudflare Tunnel on the same machine; change it to `"8000:8000"` in
`docker-compose.yml` to open it to the local network. Behind HTTPS, set
`COOKIE_SECURE=1` in `.env`.

**Bringing existing data into Docker** (do this before the first `up`, or after
`docker compose down`):

```bash
docker compose create
docker compose cp data/pycompiler.db     web:/srv/data/pycompiler.db
docker compose cp data/workspaces        web:/srv/data/workspaces
docker compose cp data/module_sources    web:/srv/data/module_sources
docker compose up -d
```

## Run it without Docker (Windows)

```powershell
.\run.ps1
```

`run.ps1` creates `.venv`, installs `backend\requirements.txt` on first run, and serves on
<http://127.0.0.1:8000>. Double-click **`start.bat`** to do the same; **`stop.ps1`** stops
whatever is listening on port 8000. Data lives in `data\`. Requires Python 3.11+
(developed on 3.12).

---

## Configuration

Copy `.env.example` to `.env` and edit what you need. The only value that matters for
security is `SECRET_KEY`; if it is missing one is generated on first start (into `.env`
locally, into the data volume under Docker).

---

## Tests

```powershell
cd backend
..\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
..\.venv\Scripts\python.exe -m pytest
```

Tests use a throwaway database and folders, never `data\`.

---

## ⚠ Security boundary

**A student's Run or Submit executes their code as a normal process, as the same user
as the server.** There is a timeout, but this is **not a security sandbox**: that code
can read the server's files (including the database) and open network connections.
Under Docker it is confined to the container and runs as an unprivileged user, which
limits the damage, but only give accounts to people you trust, and keep the site behind
a login such as Cloudflare Access.

---

## Project layout

```
backend/
  app/                 FastAPI application (Python package)
    main.py            app + page routes; serves frontend/ templates and static files
    config.py          settings from .env / environment
    db.py              SQLite schema, connection, one-off migrations
    security.py        bcrypt hashing, JWT session cookies
    deps.py            current-user dependency, trainer/student role guards
    auth.py            /auth/login · /logout · /me · /password
    dashboards.py      /api/dashboard — trainer and student overviews
    assignments.py     /api/exercises · /api/assignments · /api/submissions
    modules.py         /api/modules — upload, edit, publish, assign, run, complete
    documents.py       PDF/PPT/PPTX -> learning sections
    groq_client.py     optional Groq call that structures uploaded material
    workspace.py       per-student working folder for code runs
    seed.py            demo trainer, students and exercises
  tests/               pytest suite
  requirements.txt     runtime dependencies (installed in the Docker image)
  requirements-dev.txt + pytest
  pytest.ini

frontend/
  templates/           Jinja pages
  static/css, static/js

data/                  local runtime data (git-ignored): database, workspaces, uploads
docs/                  design notes

Dockerfile · docker-compose.yml · docker-entrypoint.sh · .dockerignore
run.ps1 · start.bat · stop.ps1 · .env.example
```

Interactive API docs are at `/docs` while the server is running.

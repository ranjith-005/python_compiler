# PyCompiler

A Colab-style Python notebook in the browser, backed by a **real IPython kernel**.

## Notebook (`/notebooks`, `/nb/{id}`) — the main app

- **Live kernel per user** — variables persist between cells, exactly like Colab
- **Rich output** — matplotlib plots render inline as PNGs, pandas DataFrames as HTML
  tables, plus `display()`, SVG and markdown output
- **Streaming** — `print()` output appears as it happens over a WebSocket, not at the end
- **`input()`** — the kernel's prompt round-trips to an inline input box in the cell
- **Interrupt / restart** — a Stop button escapes an infinite loop; Restart runtime clears
  every variable
- **Cells** — code and markdown/text cells, add, reorder, delete; `[1] [2]` execution counts
- **`.ipynb`** — upload a Colab/Jupyter notebook to open it, download yours to take it back
- **Files panel** — upload (button or drag-and-drop), browse, create folders, and a `⋮`
  menu per entry: **Open/Edit · Insert path · Download · Rename · Delete**. The panel *is*
  the kernel's working directory, so an uploaded `data.csv` is readable straight away:
  `pd.read_csv("data.csv")`. A quota bar shows storage used.
- **File viewer/editor** — click a file to open it: text files edit in Monaco and save back
  to disk (`Ctrl+S`), images preview inline, binaries and files over 2 MB say so instead of
  loading. Saved changes are visible to the kernel immediately.
- **App menu (`☰`, top-left)** — New notebook · Open notebook (lists them on demand) ·
  Make a copy · Upload/Download `.ipynb` · Run all · Restart and run all · Interrupt ·
  Clear all outputs · Keyboard shortcuts · Delete this notebook.
- **Run all** — executes top to bottom, halting at the first error (as Jupyter and Colab do)
- Outputs are stored, so a page reload shows your results again — and the kernel outlives
  the reload, so your variables are still there

Keyboard: `Shift+Enter` runs a cell and moves on, `Ctrl+Enter` runs in place.

## Auth

Email + password, bcrypt-hashed, with a JWT in an HttpOnly cookie.

> A single-file "script editor" at `/ide` existed in earlier versions and has been removed.
> Scripts saved back then were migrated into single-cell notebooks, so nothing was lost.

## Setup

```powershell
cd C:\Users\ADMIN\pycompiler
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
.\run.ps1                      # or:
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>, create an account, and start coding. The SQLite database
(`pycompiler.db`) and a `SECRET_KEY` in `.env` are created automatically on first start.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

64 tests: the kernel (state across cells, execute_result, tracebacks, inline PNG, pandas
HTML, stdin, cell timeout + interrupt, restart clearing state), the WebSocket (streaming,
persistence of outputs, `input()` round-trip, restart, cross-user rejection), the notebook
API (CRUD, positions, reorder, duplicate, clear-outputs, ownership isolation, `.ipynb`
round-trip), the file manager (upload/open/edit/download/delete, folders, quota, per-user
isolation, and path-traversal attempts such as `../../escape.txt` and `C:\Windows\...`),
and auth.

A browser walkthrough runs against a **live** server (start it first, in another terminal):

```powershell
pip install -r dev-requirements.txt
.\.venv\Scripts\python.exe tests\ui_notebook_check.py .\shots    # 74 notebook UI checks
```

It drives your installed Google Chrome headlessly through the real UI and writes numbered
screenshots to the directory you pass.

## ⚠ Security boundary

**User code runs as a normal process under your OS account.** There are *resource* limits
(a cell timeout, an output cap, one long-lived kernel per user with an idle reaper and a
cap on live kernels) but this is **not a security sandbox**. Code in a cell can read and
write your files and open network connections, and the kernel holds state between
requests.

Therefore: bind to `127.0.0.1` (the default) and treat this as a single-user / trusted-user
tool. Do **not** expose it to the internet as-is.

To harden it, launch each user's kernel inside a container and point the kernelspec written
by `app/kernel.py` at that container instead of the local interpreter.

## Layout

```
app/
  main.py       FastAPI app, page routes (/, /login, /notebooks, /nb/{id})
  config.py     settings from env (.env auto-loaded)
  db.py         SQLite connection + schema + legacy snippet→notebook migration
  security.py   bcrypt hashing, JWT session cookies
  deps.py       current-user dependencies
  auth.py       /auth/register, /auth/login, /auth/logout, /auth/me

  kernel.py     KernelSession / KernelRegistry — one IPython kernel per user
  ws.py         /ws/kernel/{id} — streaming execution, interrupt, restart, input()
  notebooks.py  /api/notebooks… CRUD, cells, reorder, duplicate, .ipynb import/export
  workspace.py  per-user folder + path-traversal defence (resolve_within, safe_name)
  files.py      /api/files… upload, browse, open/save, download, rename, delete

  templates/    base.html, login.html, notebooks.html, notebook.html
  static/       css/{styles,colab}.css, js/{auth,notebook,notebooks_home}.js
tests/          test_kernel.py, test_ws.py, test_notebooks.py, test_files.py,
                test_auth.py, ui_notebook_check.py
```

Runtime artifacts: `.kernels/` (generated kernelspec pinned to the venv) and
`workspaces/user_<id>/` (each kernel's working directory — files your notebook writes land
here).

Interactive API docs are at `/docs` while the server is running.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Shift+Enter` | Run cell, then select the next one |
| `Ctrl+Enter` | Run cell and stay on it |
| `Ctrl+S` | Save the file open in the file editor |
| `Esc` | Close a menu or dialog |

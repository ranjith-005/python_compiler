"""Phase C: learning modules (reqs 14, 15, 17; student reqs 1, 2)."""

import io
import json

from conftest import register, register_trainer


def login(client, email, password="password123"):
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res


def notebook_bytes(cells):
    """A minimal .ipynb the uploader can read."""
    doc = {
        "cells": [
            {
                "cell_type": kind,
                "metadata": {},
                "source": source.splitlines(keepends=True),
                **({"outputs": [], "execution_count": None} if kind == "code" else {}),
            }
            for kind, source in cells
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return io.BytesIO(json.dumps(doc).encode("utf-8"))


LOOPS = [
    ("markdown", "# Loops\n\nA `for` loop repeats a block."),
    ("code", "for i in range(3):\n    print(i)"),
    ("markdown", "## While loops\n\nA `while` loop runs until its test fails."),
    ("code", "n = 0\nwhile n < 2:\n    n += 1\nprint(n)"),
]


def upload_module(client, title="Loops", cells=LOOPS):
    res = client.post(
        "/api/modules",
        files={"file": ("loops.ipynb", notebook_bytes(cells), "application/json")},
        data={"title": title, "description": "Learn Python loops"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def a_module_and_student(client):
    register(client, email="s1@example.com", name="Ada Lovelace")
    client.post("/auth/logout")
    register_trainer(client)
    sid = client.get("/api/students").json()[0]["id"]
    mod = upload_module(client)
    assigned = client.post(f"/api/modules/{mod['id']}/assign", json={"assign_to": [sid]})
    assert assigned.status_code == 200, assigned.text
    return sid, mod


# ── requirements 14 and 15: upload a module, do not build it in the UI ─────


def test_uploading_a_notebook_becomes_content_and_code_blocks(client):
    register_trainer(client)
    mod = upload_module(client)

    detail = client.get(f"/api/modules/{mod['id']}").json()
    assert detail["title"] == "Loops"
    kinds = [b["kind"] for b in detail["blocks"]]
    assert kinds == ["content", "code", "content", "code"]
    assert detail["blocks"][0]["source"].startswith("# Loops")
    assert "for i in range(3)" in detail["blocks"][1]["source"]
    assert detail["code_blocks"] == 2


def test_a_module_needs_a_notebook(client):
    register_trainer(client)
    res = client.post(
        "/api/modules",
        files={"file": ("notes.txt", io.BytesIO(b"not a notebook"), "text/plain")},
        data={"title": "Bad"},
    )
    assert res.status_code == 400


def test_students_cannot_upload_modules(client):
    register(client)
    res = client.post(
        "/api/modules",
        files={"file": ("loops.ipynb", notebook_bytes(LOOPS), "application/json")},
        data={"title": "Nope"},
    )
    assert res.status_code == 403


# ── student req 1: the student reaches assigned modules ────────────────────


def test_an_assigned_module_reaches_the_student(client):
    sid, mod = a_module_and_student(client)
    client.post("/auth/logout")
    login(client, "s1@example.com")

    mine = client.get("/api/modules").json()
    assert [m["id"] for m in mine] == [mod["id"]]
    assert mine[0]["progress"] == 0

    detail = client.get(f"/api/modules/{mod['id']}").json()
    assert [b["kind"] for b in detail["blocks"]] == ["content", "code", "content", "code"]

    for path in ("/student/modules", f"/student/modules/{mod['id']}"):
        assert client.get(path, follow_redirects=False).status_code == 200, path


def test_an_unassigned_module_is_invisible_to_a_student(client):
    register(client, email="s1@example.com")
    client.post("/auth/logout")
    register_trainer(client)
    mod = upload_module(client)  # never assigned
    client.post("/auth/logout")
    login(client, "s1@example.com")

    assert client.get("/api/modules").json() == []
    assert client.get(f"/api/modules/{mod['id']}").status_code == 404


# ── student req 2: progress comes from the code the student ran ────────────


def test_running_a_code_block_advances_progress(client):
    sid, mod = a_module_and_student(client)
    client.post("/auth/logout")
    login(client, "s1@example.com")

    blocks = [b for b in client.get(f"/api/modules/{mod['id']}").json()["blocks"] if b["kind"] == "code"]
    first, second = blocks[0], blocks[1]

    run = client.post(
        f"/api/modules/{mod['id']}/blocks/{first['id']}/run",
        json={"code": "print('hello')"},
    )
    assert run.status_code == 200, run.text
    assert run.json()["ok"] is True
    assert run.json()["stdout"].strip() == "hello"

    assert client.get("/api/modules").json()[0]["progress"] == 50

    # A block that raises does not count towards progress.
    bad = client.post(
        f"/api/modules/{mod['id']}/blocks/{second['id']}/run",
        json={"code": "1 / 0"},
    )
    assert bad.status_code == 200
    assert bad.json()["ok"] is False
    assert "ZeroDivisionError" in bad.json()["stderr"]
    assert client.get("/api/modules").json()[0]["progress"] == 50

    # Fixing it does.
    good = client.post(
        f"/api/modules/{mod['id']}/blocks/{second['id']}/run",
        json={"code": "print(2)"},
    )
    assert good.json()["ok"] is True
    assert client.get("/api/modules").json()[0]["progress"] == 100


def test_a_student_cannot_run_a_block_of_an_unassigned_module(client):
    register(client, email="s1@example.com")
    client.post("/auth/logout")
    register_trainer(client)
    mod = upload_module(client)
    block = [b for b in client.get(f"/api/modules/{mod['id']}").json()["blocks"] if b["kind"] == "code"][0]
    client.post("/auth/logout")
    login(client, "s1@example.com")

    res = client.post(
        f"/api/modules/{mod['id']}/blocks/{block['id']}/run", json={"code": "print(1)"}
    )
    assert res.status_code == 404


# ── requirement 17: the trainer reviews module completion ──────────────────


def test_the_trainer_sees_each_student_progress_through_a_module(client):
    sid, mod = a_module_and_student(client)
    client.post("/auth/logout")
    login(client, "s1@example.com")
    block = [b for b in client.get(f"/api/modules/{mod['id']}").json()["blocks"] if b["kind"] == "code"][0]
    client.post(f"/api/modules/{mod['id']}/blocks/{block['id']}/run", json={"code": "print(1)"})

    client.post("/auth/logout")
    login(client, "trainer@example.com")
    detail = client.get(f"/api/modules/{mod['id']}").json()
    row = detail["students"][0]
    assert row["id"] == sid
    assert row["progress"] == 50
    assert row["completed_blocks"] == 1

    # And it shows on the student's own detail page data (req 17).
    student = client.get(f"/api/students/{sid}").json()
    assert student["modules"][0]["title"] == "Loops"
    assert student["modules"][0]["progress"] == 50

    for path in ("/trainer/modules", f"/trainer/modules/{mod['id']}"):
        assert client.get(path, follow_redirects=False).status_code == 200, path


def test_module_pages_are_role_guarded(client):
    sid, mod = a_module_and_student(client)
    client.post("/auth/logout")
    login(client, "s1@example.com")
    assert client.get("/trainer/modules", follow_redirects=False).headers["location"] == "/student"
    assert client.post(f"/api/modules/{mod['id']}/assign", json={"assign_to": [sid]}).status_code == 403

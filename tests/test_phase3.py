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


def test_the_backfill_copies_notebook_code_in_order_and_skips_markdown(client):
    from app.db import _backfill_solution_code, create_notebook, get_conn, utcnow

    register(client)
    register_trainer(client)
    with get_conn() as conn:
        student_id = conn.execute(
            "SELECT id FROM users WHERE role = 'student'"
        ).fetchone()["id"]
        trainer_id = conn.execute(
            "SELECT id FROM users WHERE role = 'trainer'"
        ).fetchone()["id"]

        notebook_id = create_notebook(
            conn,
            student_id,
            "work.ipynb",
            [
                ("code", "a = 1"),
                ("markdown", "## notes the student wrote"),
                ("code", "print(a)"),
            ],
        )

        now = utcnow()
        cur = conn.execute(
            "INSERT INTO exercises (trainer_id, title, created_at, updated_at)"
            " VALUES (?, 'Ex', ?, ?)",
            (trainer_id, now, now),
        )
        exercise_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO assignments"
            " (exercise_id, student_id, assigned_by, assigned_at, notebook_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (exercise_id, student_id, trainer_id, now, notebook_id),
        )
        assignment_id = cur.lastrowid

        # The guard already fired (with nothing to copy) during the client
        # fixture's init_db(). Clear it so the backfill runs again here, and
        # reset solution_code to '' so the row matches the backfill's filter.
        conn.execute("DELETE FROM migrations WHERE key = 'notebook_code_to_solution_v1'")
        conn.execute(
            "UPDATE assignments SET solution_code = '' WHERE id = ?", (assignment_id,)
        )

        _backfill_solution_code(conn)

        carried = conn.execute(
            "SELECT solution_code FROM assignments WHERE id = ?", (assignment_id,)
        ).fetchone()["solution_code"]

    assert carried == "a = 1\n\nprint(a)"


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


def test_run_truncates_runaway_output(client):
    assignment_id = _make_assignment(client)
    body = client.post(f"/api/assignments/{assignment_id}/run", json={
        "code": "for _ in range(200000): print('x' * 100)", "stdin": "",
    }).json()
    assert body["truncated"] is True
    assert len(body["stdout"]) <= 64_000


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
    from app.db import get_conn

    assignment_id = _make_assignment(client)
    response = client.post(f"/api/assignments/{assignment_id}/submit")
    assert response.status_code == 409
    assert "before submitting" in response.json()["detail"].lower()

    # A rejected submit (unsaved/empty code) must not leave a submission
    # row behind — nothing was actually graded.
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM submissions WHERE assignment_id = ?", (assignment_id,)
        ).fetchone()[0]
    assert count == 0


def test_another_students_assignment_is_not_reachable(client):
    assignment_id = _make_assignment(client)
    client.cookies.clear()
    register(client, email="intruder@example.com")
    for call in (
        lambda: client.post(f"/api/assignments/{assignment_id}/run", json={"code": "1", "stdin": ""}),
        lambda: client.patch(f"/api/assignments/{assignment_id}/code", json={"code": "1", "stdin": ""}),
    ):
        assert call().status_code in (403, 404)


def test_opening_an_exercise_no_longer_creates_a_notebook(client):
    assignment_id = _make_assignment(client)
    before = len(client.get("/api/notebooks").json())
    client.post(f"/api/assignments/{assignment_id}/open")
    after = client.get("/api/notebooks").json()
    assert len(after) == before, "opening an exercise must not create a notebook"


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

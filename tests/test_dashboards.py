"""Trainer and student dashboards, and the assignment loop behind them."""

from conftest import register, register_trainer


def make_exercise(client, assign_to, title="Sum of two numbers", status="published", due=None):
    response = client.post(
        "/api/exercises",
        json={
            "title": title,
            "problem_statement": "Read two integers and print their sum.",
            "sample_input": "3\n4",
            "sample_output": "7",
            "starter_code": "a = int(input())\nb = int(input())\n",
            "status": status,
            "due_date": due,
            "test_cases": [
                {"stdin": "3\n4", "expected_output": "7", "is_hidden": False},
                {"stdin": "-5\n5", "expected_output": "0", "is_hidden": True},
            ],
            "assign_to": assign_to,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def student_id(client, email):
    return next(s["id"] for s in client.get("/api/students").json() if s["email"] == email)


# ── roles and access (SRS §1, §20) ──────────────────────────────────────────


def test_registration_reports_its_portal(client):
    body = register(client).json()
    assert body["role"] == "student"
    assert body["home"] == "/student"

    client.post("/auth/logout")
    body = register_trainer(client).json()
    assert body["role"] == "trainer"
    assert body["home"] == "/trainer"


def test_each_dashboard_rejects_the_other_role(client):
    register(client)
    assert client.get("/api/dashboard/trainer").status_code == 403
    assert client.get("/api/dashboard/student").status_code == 200
    assert client.get("/student", follow_redirects=False).status_code == 200
    assert client.get("/trainer", follow_redirects=False).headers["location"] == "/student"

    client.post("/auth/logout")
    register_trainer(client)
    assert client.get("/api/dashboard/student").status_code == 403
    assert client.get("/api/dashboard/trainer").status_code == 200
    assert client.get("/student", follow_redirects=False).headers["location"] == "/trainer"


def test_dashboards_require_a_session(client):
    assert client.get("/api/dashboard/trainer").status_code == 401
    assert client.get("/api/dashboard/student").status_code == 401
    assert client.get("/trainer", follow_redirects=False).headers["location"] == "/login"
    assert client.get("/student", follow_redirects=False).headers["location"] == "/login"


def test_students_cannot_create_exercises(client):
    register(client)
    assert client.post("/api/exercises", json={"title": "Nope"}).status_code == 403
    assert client.get("/api/students").status_code == 403


# ── trainer overview (SRS §2) ───────────────────────────────────────────────


def test_trainer_overview_counts_reflect_the_data(client):
    register(client, "a@example.com")
    client.post("/auth/logout")
    register(client, "b@example.com")
    client.post("/auth/logout")
    register_trainer(client)

    ids = [s["id"] for s in client.get("/api/students").json()]
    make_exercise(client, ids)
    make_exercise(client, [], title="Draft one", status="draft")

    data = client.get("/api/dashboard/trainer").json()
    assert data["stats"]["students"] == 2
    assert data["stats"]["exercises"] == 2
    assert data["stats"]["published"] == 1
    assert data["stats"]["drafts"] == 1
    # Both students have work outstanding and nothing has been submitted yet.
    assert data["stats"]["pending"] == 2
    assert data["stats"]["awaiting_review"] == 0
    assert [x["title"] for x in data["exercises"]] == ["Draft one", "Sum of two numbers"]
    assert len(data["students"]) == 2
    assert all(s["progress"] == 0 for s in data["students"])


def test_a_draft_is_not_assigned_or_shown_to_students(client):
    register(client, "a@example.com")
    client.post("/auth/logout")
    register_trainer(client)
    make_exercise(client, [student_id(client, "a@example.com")], status="draft")

    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "a@example.com", "password": "password123"})
    assert client.get("/api/dashboard/student").json()["assignments"] == []


def test_one_trainer_cannot_see_another_trainers_work(client):
    register(client, "a@example.com")
    client.post("/auth/logout")
    register_trainer(client, "t1@example.com")
    make_exercise(client, [student_id(client, "a@example.com")], title="Mine")

    client.post("/auth/logout")
    register_trainer(client, "t2@example.com")
    data = client.get("/api/dashboard/trainer").json()
    assert data["exercises"] == []
    assert data["stats"]["exercises"] == 0
    assert data["stats"]["pending"] == 0
    # The student roster is shared, but none of their work belongs to this trainer.
    assert [s["assigned"] for s in data["students"]] == [0]


# ── student overview (SRS §3) ───────────────────────────────────────────────


def test_assignment_reaches_the_student_dashboard_with_a_notification(client):
    register(client, "a@example.com")
    client.post("/auth/logout")
    register_trainer(client)
    make_exercise(client, [student_id(client, "a@example.com")], due="2030-01-01T09:00")

    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "a@example.com", "password": "password123"})
    data = client.get("/api/dashboard/student").json()

    assert data["stats"]["assigned"] == 1
    assignment = data["assignments"][0]
    assert assignment["title"] == "Sum of two numbers"
    assert assignment["status"] == "assigned"
    assert assignment["due_date"].startswith("2030-01-01")
    assert assignment["overdue"] is False
    assert "print their sum" in assignment["preview"]
    # Nothing has been opened yet, so "continue" points at the only open item.
    assert data["resume"]["id"] == assignment["id"]
    assert data["unread"] == 1
    assert "Sum of two numbers" in data["notifications"][0]["title"]


def test_overdue_work_is_flagged(client):
    register(client, "a@example.com")
    client.post("/auth/logout")
    register_trainer(client)
    make_exercise(client, [student_id(client, "a@example.com")], due="2020-01-01T09:00")

    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "a@example.com", "password": "password123"})
    data = client.get("/api/dashboard/student").json()
    assert data["assignments"][0]["overdue"] is True
    assert data["stats"]["overdue"] == 1


def test_opening_an_assignment_creates_a_notebook_once(client):
    register(client, "a@example.com")
    client.post("/auth/logout")
    register_trainer(client)
    make_exercise(client, [student_id(client, "a@example.com")])

    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "a@example.com", "password": "password123"})
    assignment_id = client.get("/api/dashboard/student").json()["assignments"][0]["id"]

    first = client.post(f"/api/assignments/{assignment_id}/open").json()
    assert first["status"] == "in_progress"
    again = client.post(f"/api/assignments/{assignment_id}/open").json()
    assert again["notebook_id"] == first["notebook_id"]

    cells = client.get(f"/api/notebooks/{first['notebook_id']}").json()["cells"]
    assert cells[0]["cell_type"] == "markdown"
    assert "Sum of two numbers" in cells[0]["source"]
    assert cells[1]["source"].startswith("a = int(input())")

    data = client.get("/api/dashboard/student").json()
    assert data["stats"]["in_progress"] == 1
    assert data["resume"]["last_opened_at"]


def test_a_student_cannot_open_someone_elses_assignment(client):
    register(client, "a@example.com")
    client.post("/auth/logout")
    register(client, "b@example.com")
    client.post("/auth/logout")
    register_trainer(client)
    make_exercise(client, [student_id(client, "a@example.com")])

    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "a@example.com", "password": "password123"})
    assignment_id = client.get("/api/dashboard/student").json()["assignments"][0]["id"]

    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "b@example.com", "password": "password123"})
    assert client.post(f"/api/assignments/{assignment_id}/open").status_code == 404
    assert client.get(f"/api/assignments/{assignment_id}").status_code == 404


# ── submission, evaluation and review (SRS §11-§14) ─────────────────────────


def solve(client, assignment_id, code):
    """Save `code` as the assignment's solution and submit it."""
    client.patch(f"/api/assignments/{assignment_id}/code", json={"code": code, "stdin": ""})
    return client.post(f"/api/assignments/{assignment_id}/submit").json()


def setup_one_assignment(client):
    register(client, "a@example.com")
    client.post("/auth/logout")
    register_trainer(client)
    make_exercise(client, [student_id(client, "a@example.com")])
    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "a@example.com", "password": "password123"})
    return client.get("/api/dashboard/student").json()["assignments"][0]["id"]


def test_a_correct_solution_passes_every_test_case(client):
    assignment_id = setup_one_assignment(client)
    result = solve(client, assignment_id, "a = int(input())\nb = int(input())\nprint(a + b)")
    assert result["result"] == "accepted"
    # The hidden case counts towards the verdict as well.
    assert (result["passed"], result["total"]) == (2, 2)

    data = client.get("/api/dashboard/student").json()
    assert data["stats"]["submitted"] == 1
    assert data["assignments"][0]["status"] == "submitted"


def test_wrong_and_broken_solutions_get_their_own_verdicts(client):
    assignment_id = setup_one_assignment(client)

    wrong = solve(client, assignment_id, "a = int(input())\nb = int(input())\nprint(a - b)")
    assert wrong["result"] == "wrong_answer"
    assert wrong["passed"] == 0

    broken = solve(client, assignment_id, 'print("unclosed')
    assert broken["result"] == "syntax_error"

    crash = solve(client, assignment_id, "raise ValueError('boom')")
    assert crash["result"] == "runtime_error"


def test_resubmitting_supersedes_the_queued_attempt(client):
    assignment_id = setup_one_assignment(client)
    solve(client, assignment_id, "print(0)")
    solve(client, assignment_id, "a = int(input())\nb = int(input())\nprint(a + b)")

    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "trainer@example.com", "password": "password123"})
    data = client.get("/api/dashboard/trainer").json()
    assert data["stats"]["awaiting_review"] == 1
    assert data["review_queue"][0]["result"] == "accepted"

    # Both attempts remain in the history (SRS §15).
    history = client.get(f"/api/assignments/{assignment_id}").json()["history"]
    assert len(history) == 2


def test_review_approves_and_notifies_the_student(client):
    assignment_id = setup_one_assignment(client)
    solve(client, assignment_id, "a = int(input())\nb = int(input())\nprint(a + b)")

    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "trainer@example.com", "password": "password123"})
    queued = client.get("/api/dashboard/trainer").json()["review_queue"][0]
    assert queued["student_email"] == "a@example.com"
    assert "print(a + b)" in queued["code"]

    verdict = client.post(
        f"/api/submissions/{queued['id']}/review",
        json={"action": "approve", "comment": "Nicely done."},
    ).json()
    assert verdict["assignment_status"] == "approved"

    after = client.get("/api/dashboard/trainer").json()
    assert after["stats"]["awaiting_review"] == 0
    assert after["review_queue"] == []

    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "a@example.com", "password": "password123"})
    data = client.get("/api/dashboard/student").json()
    assert data["stats"]["completed"] == 1
    assert data["assignments"][0]["comment"] == "Nicely done."
    assert data["resume"] is None
    assert any("approved" in n["title"].lower() for n in data["notifications"])


def test_requesting_changes_reopens_the_assignment(client):
    assignment_id = setup_one_assignment(client)
    solve(client, assignment_id, "print(0)")

    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "trainer@example.com", "password": "password123"})
    submission_id = client.get("/api/dashboard/trainer").json()["review_queue"][0]["id"]
    client.post(
        f"/api/submissions/{submission_id}/review",
        json={"action": "request_changes", "comment": "Read the input first."},
    )

    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "a@example.com", "password": "password123"})
    data = client.get("/api/dashboard/student").json()
    assert data["stats"]["changes_requested"] == 1
    assert data["assignments"][0]["comment"] == "Read the input first."
    # It counts as open work again, so it comes back as the thing to continue.
    assert data["resume"]["id"] == assignment_id

    # And the student can fix it and resubmit.
    again = solve(client, assignment_id, "a = int(input())\nb = int(input())\nprint(a + b)")
    assert again["result"] == "accepted"


def test_a_closed_assignment_cannot_be_resubmitted(client):
    assignment_id = setup_one_assignment(client)
    solve(client, assignment_id, "a = int(input())\nb = int(input())\nprint(a + b)")

    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "trainer@example.com", "password": "password123"})
    submission_id = client.get("/api/dashboard/trainer").json()["review_queue"][0]["id"]
    client.post(f"/api/submissions/{submission_id}/review", json={"action": "complete"})

    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "a@example.com", "password": "password123"})
    assert client.post(f"/api/assignments/{assignment_id}/submit").status_code == 409


def test_a_trainer_cannot_review_another_trainers_submission(client):
    assignment_id = setup_one_assignment(client)
    solve(client, assignment_id, "print(0)")

    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "trainer@example.com", "password": "password123"})
    submission_id = client.get("/api/dashboard/trainer").json()["review_queue"][0]["id"]

    client.post("/auth/logout")
    register_trainer(client, "other@example.com")
    response = client.post(
        f"/api/submissions/{submission_id}/review", json={"action": "approve"}
    )
    assert response.status_code == 404


# ── notifications (SRS §17) ─────────────────────────────────────────────────


def test_notifications_can_be_marked_read(client):
    register(client, "a@example.com")
    client.post("/auth/logout")
    register_trainer(client)
    make_exercise(client, [student_id(client, "a@example.com")])

    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "a@example.com", "password": "password123"})
    assert client.get("/api/dashboard/student").json()["unread"] == 1
    assert client.post("/api/dashboard/notifications/read").status_code == 200

    data = client.get("/api/dashboard/student").json()
    assert data["unread"] == 0
    assert len(data["notifications"]) == 1


# ── pages ───────────────────────────────────────────────────────────────────


def test_dashboard_pages_render_their_own_assets(client):
    register(client)
    page = client.get("/student")
    assert page.status_code == 200
    assert "student_dashboard.js" in page.text
    assert "dashboard.css" in page.text

    client.post("/auth/logout")
    register_trainer(client)
    page = client.get("/trainer")
    assert page.status_code == 200
    assert "trainer_dashboard.js" in page.text
    assert "Trainer One" in page.text


def test_trainer_section_pages_are_reachable(client):
    """The trainer dashboard links to /trainer/queue and /trainer/exercises,
    so both must resolve to the section page rather than 404."""
    sections = ("exercises", "queue")

    for section in sections:
        assert client.get(f"/trainer/{section}", follow_redirects=False).headers[
            "location"
        ] == "/login"

    register(client)
    for section in sections:
        assert client.get(f"/trainer/{section}", follow_redirects=False).headers[
            "location"
        ] == "/student"
    client.post("/auth/logout")

    register_trainer(client)
    for section in sections:
        resp = client.get(f"/trainer/{section}", follow_redirects=False)
        assert resp.status_code == 200, f"/trainer/{section} returned {resp.status_code}"

    # The roster page must keep its own literal route, not be swallowed by the
    # {section} parameter declared after it.
    assert client.get("/trainer/students", follow_redirects=False).status_code == 200

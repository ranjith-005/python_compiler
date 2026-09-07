"""The solve page's contract: test-case results, and reopening after a deadline.

Two behaviours the student page leans on:

  * Run grades against the test cases and reports each one -- how many passed,
    which failed, and why -- without recording anything.
  * Past the due date the editor closes. The student asks for it back, and the
    trainer answers each request individually.
"""

from datetime import datetime, timedelta, timezone

from conftest import register, register_trainer
from test_dashboards import make_exercise, student_id

STUDENT = "solver@example.com"
SUM = "a = int(input())\nb = int(input())\nprint(a + b)"
WRONG = "a = int(input())\nb = int(input())\nprint(a - b)"
CRASHES = "raise ValueError('deliberate')"
BROKEN = "def oops(:\n"


def as_student(client, email=STUDENT):
    client.cookies.clear()
    client.post("/auth/login", json={"email": email, "password": "password123"})


def as_trainer(client):
    client.cookies.clear()
    client.post("/auth/login", json={"email": "trainer@example.com", "password": "password123"})


def a_task(client, due=None, student=STUDENT, title="Sum of two numbers"):
    """A trainer, a student, and one assigned exercise. Returns its assignment id."""
    register(client, student)
    client.cookies.clear()
    register_trainer(client)
    sid = student_id(client, student)
    make_exercise(client, [sid], title=title, due=due)
    as_student(client, student)
    return next(
        a["id"]
        for a in client.get("/api/dashboard/student").json()["assignments"]
        if a["title"] == title
    )


def check(client, assignment_id, code):
    res = client.post(
        f"/api/assignments/{assignment_id}/check", json={"code": code, "stdin": ""}
    )
    assert res.status_code == 200, res.text
    return res.json()


# ── Run reports every test case (exercise reqs: input/output field) ──────────


def test_a_correct_solution_reports_every_case_passed(client):
    assignment_id = a_task(client)
    v = check(client, assignment_id, SUM)

    assert (v["passed"], v["total"]) == (2, 2)
    assert v["result"] == "accepted"
    assert len(v["cases"]) == 2
    assert all(c["passed"] for c in v["cases"])


def test_a_wrong_solution_names_which_cases_failed_and_why(client):
    assignment_id = a_task(client)
    v = check(client, assignment_id, WRONG)

    assert v["passed"] < v["total"]
    failed = [c for c in v["cases"] if not c["passed"]]
    assert failed, v["cases"]
    for case in failed:
        assert case["error"], case
    # A visible case shows the whole comparison, so the student can see the gap.
    visible = [c for c in v["cases"] if not c["hidden"]]
    assert visible
    assert "expected" in visible[0] and "actual" in visible[0]


def test_every_case_runs_even_after_one_fails(client):
    """A verdict of 1/2 must be able to say which one, so none are skipped."""
    assignment_id = a_task(client)
    v = check(client, assignment_id, WRONG)
    assert len(v["cases"]) == v["total"]
    assert [c["number"] for c in v["cases"]] == list(range(1, v["total"] + 1))


def test_a_crash_is_reported_against_the_case_that_crashed(client):
    assignment_id = a_task(client)
    v = check(client, assignment_id, CRASHES)

    assert v["result"] == "runtime_error"
    assert v["passed"] == 0
    assert any("ValueError" in (c["error"] or "") for c in v["cases"]), v["cases"]


def test_code_that_does_not_compile_says_so_without_running(client):
    assignment_id = a_task(client)
    v = check(client, assignment_id, BROKEN)

    assert v["result"] == "syntax_error"
    assert v["passed"] == 0
    assert v["detail"]


def test_a_hidden_case_reports_pass_or_fail_but_never_its_input(client):
    """Hiding a case is pointless if failing it prints the case (SRS §10)."""
    assignment_id = a_task(client)
    v = check(client, assignment_id, WRONG)

    hidden = [c for c in v["cases"] if c["hidden"]]
    assert hidden, "the seeded exercise should carry a hidden case"
    for case in hidden:
        assert "stdin" not in case
        assert "expected" not in case
        assert "actual" not in case
        assert case["error"] or case["passed"]


def test_running_the_tests_records_no_submission(client):
    """Run is not Submit: it can be pressed all day and nothing is filed."""
    assignment_id = a_task(client)
    check(client, assignment_id, SUM)
    check(client, assignment_id, WRONG)

    detail = client.get(f"/api/assignments/{assignment_id}").json()
    assert detail["history"] == []
    assert detail["status"] != "submitted"


def test_submitting_returns_the_same_per_case_detail(client):
    assignment_id = a_task(client)
    client.patch(f"/api/assignments/{assignment_id}/code", json={"code": SUM, "stdin": ""})
    v = client.post(f"/api/assignments/{assignment_id}/submit").json()

    assert (v["passed"], v["total"]) == (2, 2)
    assert len(v["cases"]) == 2


# ── the deadline closes the editor (exercise reqs: deadline) ────────────────


def overdue():
    return (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()


def test_an_overdue_exercise_is_read_only(client):
    assignment_id = a_task(client, due=overdue())

    detail = client.get(f"/api/assignments/{assignment_id}").json()
    assert detail["locked"] is True
    assert detail["past_due"] is True
    assert detail["access_request"] is None

    for call in (
        client.patch(f"/api/assignments/{assignment_id}/code", json={"code": SUM, "stdin": ""}),
        client.post(f"/api/assignments/{assignment_id}/check", json={"code": SUM, "stdin": ""}),
        client.post(f"/api/assignments/{assignment_id}/run", json={"code": SUM, "stdin": ""}),
        client.post(f"/api/assignments/{assignment_id}/submit"),
    ):
        assert call.status_code == 409, call.text
        assert "deadline" in call.json()["detail"].lower()


def test_an_exercise_still_open_is_not_locked(client):
    future = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
    assignment_id = a_task(client, due=future)
    detail = client.get(f"/api/assignments/{assignment_id}").json()
    assert detail["locked"] is False
    assert detail["past_due"] is False


def test_a_student_can_raise_one_request_and_only_one(client):
    assignment_id = a_task(client, due=overdue())

    first = client.post(
        f"/api/assignments/{assignment_id}/access-request", json={"message": "I was ill."}
    )
    assert first.status_code == 201, first.text

    again = client.post(
        f"/api/assignments/{assignment_id}/access-request", json={"message": "Please?"}
    )
    assert again.status_code == 409

    detail = client.get(f"/api/assignments/{assignment_id}").json()
    assert detail["access_request"]["status"] == "pending"
    assert detail["access_request"]["message"] == "I was ill."


def test_a_request_cannot_be_raised_before_the_deadline(client):
    future = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
    assignment_id = a_task(client, due=future)
    res = client.post(f"/api/assignments/{assignment_id}/access-request", json={"message": ""})
    assert res.status_code == 409


def test_approving_hands_the_editor_back(client):
    assignment_id = a_task(client, due=overdue())
    request_id = client.post(
        f"/api/assignments/{assignment_id}/access-request", json={"message": "I was ill."}
    ).json()["id"]

    as_trainer(client)
    decided = client.post(
        f"/api/access-requests/{request_id}/decide",
        json={"action": "approve", "message": "Finish it today."},
    )
    assert decided.status_code == 200, decided.text

    as_student(client)
    detail = client.get(f"/api/assignments/{assignment_id}").json()
    assert detail["locked"] is False
    assert detail["access_request"]["status"] == "approved"
    assert detail["access_request"]["decision_message"] == "Finish it today."

    # And the student can actually work again.
    assert client.patch(
        f"/api/assignments/{assignment_id}/code", json={"code": SUM, "stdin": ""}
    ).status_code == 200
    assert client.post(f"/api/assignments/{assignment_id}/submit").status_code == 200


def test_rejecting_leaves_it_locked_and_carries_the_reason(client):
    assignment_id = a_task(client, due=overdue())
    request_id = client.post(
        f"/api/assignments/{assignment_id}/access-request", json={"message": "Please."}
    ).json()["id"]

    as_trainer(client)
    client.post(
        f"/api/access-requests/{request_id}/decide",
        json={"action": "reject", "message": "You had three weeks."},
    )

    as_student(client)
    detail = client.get(f"/api/assignments/{assignment_id}").json()
    assert detail["locked"] is True
    assert detail["access_request"]["status"] == "rejected"
    assert detail["access_request"]["decision_message"] == "You had three weeks."
    assert client.post(f"/api/assignments/{assignment_id}/submit").status_code == 409


def test_two_students_asking_about_one_exercise_get_their_own_answers(client):
    """The decision lives on the request, so it can differ per student."""
    assignment_id = a_task(client, due=overdue())

    as_trainer(client)
    second = client.post(
        "/api/students",
        json={"email": "second@example.com", "password": "password123",
              "first_name": "Second", "last_name": "Student"},
    )
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]

    exercise_id = client.get("/api/exercises").json()[0]["id"]
    client.post(f"/api/exercises/{exercise_id}/assign", json={"assign_to": [second_id]})

    as_student(client, "second@example.com")
    other_assignment = next(
        a["id"] for a in client.get("/api/dashboard/student").json()["assignments"]
    )
    second_request = client.post(
        f"/api/assignments/{other_assignment}/access-request", json={"message": "Me too."}
    ).json()["id"]

    as_student(client)
    first_request = client.post(
        f"/api/assignments/{assignment_id}/access-request", json={"message": "And me."}
    ).json()["id"]

    as_trainer(client)
    pending = client.get("/api/access-requests?status=pending").json()
    assert len(pending) == 2
    client.post(f"/api/access-requests/{first_request}/decide",
                json={"action": "approve", "message": "Yes — by Friday."})
    client.post(f"/api/access-requests/{second_request}/decide",
                json={"action": "reject", "message": "No — you did not start it."})

    as_student(client)
    mine = client.get(f"/api/assignments/{assignment_id}").json()
    assert mine["locked"] is False
    assert mine["access_request"]["decision_message"] == "Yes — by Friday."

    as_student(client, "second@example.com")
    theirs = client.get(f"/api/assignments/{other_assignment}").json()
    assert theirs["locked"] is True
    assert theirs["access_request"]["decision_message"] == "No — you did not start it."


def test_a_decision_cannot_be_made_twice(client):
    assignment_id = a_task(client, due=overdue())
    request_id = client.post(
        f"/api/assignments/{assignment_id}/access-request", json={"message": ""}
    ).json()["id"]

    as_trainer(client)
    assert client.post(f"/api/access-requests/{request_id}/decide",
                       json={"action": "approve", "message": ""}).status_code == 200
    assert client.post(f"/api/access-requests/{request_id}/decide",
                       json={"action": "reject", "message": ""}).status_code == 409


def test_one_trainer_cannot_decide_another_trainers_request(client):
    assignment_id = a_task(client, due=overdue())
    request_id = client.post(
        f"/api/assignments/{assignment_id}/access-request", json={"message": ""}
    ).json()["id"]

    client.cookies.clear()
    register_trainer(client, "other.trainer@example.com")
    assert client.get("/api/access-requests").json() == []
    assert client.post(f"/api/access-requests/{request_id}/decide",
                       json={"action": "approve", "message": ""}).status_code == 404


def test_students_cannot_decide_their_own_request(client):
    assignment_id = a_task(client, due=overdue())
    request_id = client.post(
        f"/api/assignments/{assignment_id}/access-request", json={"message": ""}
    ).json()["id"]
    assert client.post(f"/api/access-requests/{request_id}/decide",
                       json={"action": "approve", "message": ""}).status_code == 403


# ── the trainer enrols students (sign-in page has no sign-up) ───────────────


def test_a_trainer_creates_a_student_account_that_can_sign_in(client):
    register_trainer(client)
    created = client.post(
        "/api/students",
        json={"email": "enrolled@example.com", "password": "password123",
              "first_name": "New", "last_name": "Student"},
    )
    assert created.status_code == 201, created.text

    client.cookies.clear()
    signed_in = client.post(
        "/auth/login", json={"email": "enrolled@example.com", "password": "password123"}
    )
    assert signed_in.status_code == 200
    assert signed_in.json()["role"] == "student"


def test_enrolling_the_same_email_twice_is_refused(client):
    register_trainer(client)
    body = {"email": "dupe@example.com", "password": "password123",
            "first_name": "A", "last_name": "B"}
    assert client.post("/api/students", json=body).status_code == 201
    assert client.post("/api/students", json=body).status_code == 409


def test_students_cannot_enrol_anyone(client):
    a_task(client)
    res = client.post(
        "/api/students",
        json={"email": "sneaky@example.com", "password": "password123",
              "first_name": "S", "last_name": "S"},
    )
    assert res.status_code == 403


def test_the_sign_in_page_offers_no_way_to_create_an_account(client):
    html = client.get("/login").text
    assert "Create account" not in html
    assert "Create an account" not in html
    assert 'id="register-only"' not in html
    # And no placeholders repeating the labels next to them.
    assert "you@example.com" not in html

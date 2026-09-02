"""Phase B: detail pages, date filters and the query/warning workflow."""

from conftest import register, register_trainer


def login(client, email, password="password123"):
    """Sign back in to an account that already exists."""
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res


def make_exercise(client, title="Sum two numbers", status="published", students=None):
    """Create an exercise as the signed-in trainer and return its row."""
    body = {
        "title": title,
        "problem_statement": "Read two integers and print their sum.",
        "input_format": "two integers",
        "output_format": "one integer",
        "sample_input": "1 2",
        "sample_output": "3",
        "status": status,
        "assign_to": students or [],
        "test_cases": [{"stdin": "1 2", "expected_output": "3", "is_hidden": False}],
    }
    res = client.post("/api/exercises", json=body)
    assert res.status_code == 201, res.text
    return {**body, **res.json()}


def a_student_and_trainer(client):
    """A student with one published exercise assigned by a trainer."""
    register(client, email="s1@example.com", name="Ada Lovelace")
    me = client.get("/api/dashboard/student").json()
    client.post("/auth/logout")
    register_trainer(client)
    students = client.get("/api/students").json()
    sid = students[0]["id"]
    ex = make_exercise(client, students=[sid])
    return sid, ex, me


# ── requirement 2: student detail, personal info, per-exercise timeline ─────


def test_student_detail_page_and_api(client):
    sid, ex, _ = a_student_and_trainer(client)

    detail = client.get(f"/api/students/{sid}").json()
    assert detail["student"]["full_name"] == "Ada Lovelace"
    assert detail["student"]["email"] == "s1@example.com"
    assert len(detail["exercises"]) == 1
    assert detail["exercises"][0]["title"] == ex["title"]
    assert "progress" in detail

    for path in (
        f"/trainer/students/{sid}",
        f"/trainer/students/{sid}/profile",
        f"/trainer/students/{sid}/exercises/{ex['id']}",
    ):
        assert client.get(path, follow_redirects=False).status_code == 200, path


def test_student_detail_is_trainer_only(client):
    sid, ex, _ = a_student_and_trainer(client)
    client.post("/auth/logout")
    register(client, email="other@example.com")
    assert client.get(f"/api/students/{sid}").status_code == 403
    assert client.get(f"/trainer/students/{sid}", follow_redirects=False).headers[
        "location"
    ] == "/student"


def test_the_roster_reports_how_many_students_exist(client):
    register(client, email="a@example.com")
    client.post("/auth/logout")
    register(client, email="b@example.com")
    client.post("/auth/logout")
    register_trainer(client)
    assert len(client.get("/api/students").json()) == 2
    assert 'id="student-count"' in client.get("/trainer/students").text


# ── requirement 8: exercise detail page ────────────────────────────────────


def test_exercise_detail_carries_everything(client):
    sid, ex, _ = a_student_and_trainer(client)

    detail = client.get(f"/api/exercises/{ex['id']}").json()
    assert detail["title"] == ex["title"]
    assert detail["problem_statement"]
    assert len(detail["test_cases"]) == 1
    assert [s["id"] for s in detail["students"]] == [sid]
    assert "submissions" in detail

    assert client.get(f"/trainer/exercises/{ex['id']}", follow_redirects=False).status_code == 200


def test_one_trainer_cannot_open_anothers_exercise(client):
    _, ex, _ = a_student_and_trainer(client)
    client.post("/auth/logout")
    register_trainer(client, email="other-trainer@example.com")
    assert client.get(f"/api/exercises/{ex['id']}").status_code == 404


# ── requirements 6 and 13: draft page, new-exercise page ───────────────────


def test_drafts_have_their_own_page_and_can_be_assigned(client):
    register(client, email="s1@example.com")
    client.post("/auth/logout")
    register_trainer(client)
    sid = client.get("/api/students").json()[0]["id"]
    draft = make_exercise(client, title="Draft one", status="draft")

    assert client.get("/trainer/exercises/drafts", follow_redirects=False).status_code == 200
    assert client.get("/trainer/exercises/new", follow_redirects=False).status_code == 200

    listed = client.get("/api/exercises?status=draft").json()
    assert [e["id"] for e in listed] == [draft["id"]]

    # Assigning from the drafts page publishes it and creates the assignment.
    res = client.post(f"/api/exercises/{draft['id']}/assign", json={"assign_to": [sid]})
    assert res.status_code == 200, res.text
    after = client.get(f"/api/exercises/{draft['id']}").json()
    assert after["status"] == "published"
    assert [s["id"] for s in after["students"]] == [sid]


# ── requirement 12: query with warning details ─────────────────────────────


def test_trainer_raises_a_query_and_the_student_replies(client):
    sid, ex, _ = a_student_and_trainer(client)
    assignment = client.get("/api/dashboard/trainer").json()["pending"][0]

    res = client.post(
        f"/api/assignments/{assignment['id']}/query",
        json={"severity": "warning", "message": "Due tomorrow and nothing submitted."},
    )
    assert res.status_code == 201, res.text
    query_id = res.json()["id"]

    client.post("/auth/logout")
    login(client, "s1@example.com")
    student_view = client.get("/api/dashboard/student").json()
    assert student_view["queries"][0]["message"] == "Due tomorrow and nothing submitted."
    assert student_view["queries"][0]["severity"] == "warning"

    reply = client.post(f"/api/queries/{query_id}/reply", json={"reply": "Submitting tonight."})
    assert reply.status_code == 200, reply.text

    client.post("/auth/logout")
    login(client, "trainer@example.com")
    back = client.get("/api/dashboard/trainer").json()["queries"]
    assert back[0]["reply"] == "Submitting tonight."


def test_a_student_cannot_raise_a_query(client):
    sid, ex, _ = a_student_and_trainer(client)
    assignment = client.get("/api/dashboard/trainer").json()["pending"][0]
    client.post("/auth/logout")
    login(client, "s1@example.com")
    res = client.post(
        f"/api/assignments/{assignment['id']}/query",
        json={"severity": "warning", "message": "nope"},
    )
    assert res.status_code == 403


def test_a_query_rejects_an_unknown_severity(client):
    sid, ex, _ = a_student_and_trainer(client)
    assignment = client.get("/api/dashboard/trainer").json()["pending"][0]
    res = client.post(
        f"/api/assignments/{assignment['id']}/query",
        json={"severity": "catastrophe", "message": "x"},
    )
    assert res.status_code == 422


# ── requirement 13: the review page replaces the modal ─────────────────────


def test_review_has_its_own_page_and_the_modal_is_gone(client):
    sid, ex, _ = a_student_and_trainer(client)
    html = client.get("/trainer").text
    assert 'id="exercise-sheet"' not in html, "the new-exercise modal should be a page now"
    assert 'id="review-sheet"' not in html, "the review modal should be a page now"
    assert 'href="/trainer/exercises/new"' in html

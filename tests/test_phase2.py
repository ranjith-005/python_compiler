from datetime import datetime, timedelta, timezone

from conftest import register, register_trainer
from test_dashboards import make_exercise, solve, student_id


def test_pages_render_the_accounts_theme_server_side(client):
    register(client)
    client.patch("/api/settings/theme", json={"theme": "light"})
    for path in ("/student", "/student/exercises", "/activity", "/profile", "/settings"):
        html = client.get(path).text
        assert 'data-theme="light"' in html, path


def test_signed_out_pages_fall_back_to_system(client):
    html = client.get("/login").text
    assert 'data-theme="system"' in html
    assert 'data-theme-source="anonymous"' in html


def test_a_signed_in_account_is_marked_authoritative(client):
    register(client)
    html = client.get("/student").text
    assert 'data-theme-source="account"' in html


def test_theme_change_is_reflected_on_the_next_page_load(client):
    register(client)
    assert 'data-theme="system"' in client.get("/student").text
    client.patch("/api/settings/theme", json={"theme": "dark"})
    assert 'data-theme="dark"' in client.get("/student").text


def test_password_change_signs_out_other_devices(client):
    register(client)
    stale = dict(client.cookies)          # this browser's cookie, captured before the change

    client.post("/auth/password", json={
        "current_password": "password123",
        "new_password": "newpassword456",
        "confirm_password": "newpassword456",
    })
    # The device that changed it stays signed in (it got a fresh cookie).
    assert client.get("/auth/me").status_code == 200

    # A different device still holding the old cookie is rejected.
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as elsewhere:
        elsewhere.cookies.update(stale)
        assert elsewhere.get("/auth/me").status_code == 401


def test_password_change_closes_the_kernel_socket_too(client):
    register(client)
    notebook_id = client.get("/api/notebooks").json()[0]["id"]
    stale = dict(client.cookies)

    # The socket works before the change.
    with client.websocket_connect(f"/ws/kernel/{notebook_id}"):
        pass

    client.post("/auth/password", json={
        "current_password": "password123",
        "new_password": "newpassword456",
        "confirm_password": "newpassword456",
    })

    # A device still holding the old cookie cannot open a kernel.
    from fastapi.testclient import TestClient
    from app.main import app
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with TestClient(app) as elsewhere:
        elsewhere.cookies.update(stale)
        with pytest.raises(WebSocketDisconnect):
            with elsewhere.websocket_connect(f"/ws/kernel/{notebook_id}"):
                pass


def test_no_api_response_exposes_an_email_as_a_name(client):
    register_trainer(client)
    client.cookies.clear()
    register(client, email="nameless.student@example.com")
    client.cookies.clear()
    # A second, distinct trainer account: the first email is already taken, and
    # the roster this endpoint returns is not scoped to who is asking anyway.
    register_trainer(client, email="trainer2@example.com")

    roster = client.get("/api/dashboard/trainer").json()["students"]
    assert roster, "expected the student in the roster"
    for row in roster:
        assert row["display"] == "Nameless Student"
        assert "@" not in row["display"]


def test_section_pages_highlight_their_own_nav_section(client):
    register_trainer(client)
    # The queue is not the Exercises section; it must not mark Exercises active.
    queue = client.get("/trainer/queue").text
    assert 'class="cb-link active" href="/trainer/students"' not in queue
    exercises = client.get("/trainer/exercises").text
    assert "active" in exercises


def test_exercise_titles_are_not_interpolated_as_html(client):
    register_trainer(client)
    client.post("/api/exercises", json={
        "title": "<img src=x onerror=alert(1)>",
        "problem_statement": "safe",
        "status": "published",
        "test_cases": [], "assign_to": [],
    })
    # The page is a shell; the title must not appear in the served HTML at all,
    # and the script must build rows with el(), never innerHTML.
    page = client.get("/trainer/exercises").text
    assert "onerror" not in page
    script = open("app/static/js/trainer_section.js", encoding="utf-8").read()
    assert "innerHTML" not in script


def test_trainer_dashboard_is_cards_only(client):
    register_trainer(client)
    html = client.get("/trainer").text
    for gone in ("Submissions awaiting review", "Pending submissions",
                 "Coding exercises", "Upcoming deadlines", "+ New exercise"):
        assert gone not in html, gone
    # The topbar's Exercises dropdown legitimately has a "Drafts" link (it is
    # unrelated to this page and stays); the dashboard's own quick row, which
    # used to duplicate it, is what must be gone.
    assert 'class="quick"' not in html
    assert 'id="stats"' in html


# ── Task 6: the two new trainer pages, and the roster by name ───────────────


def test_new_trainer_pages_are_guarded_and_render(client):
    register_trainer(client)
    for path in ("/trainer/pending", "/trainer/completed"):
        assert client.get(path).status_code == 200
    client.cookies.clear()
    register(client, email="s2@example.com")
    for path in ("/trainer/pending", "/trainer/completed"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "/student"


def test_student_detail_counts_late_submissions(client):
    # An assignment submitted after its due date is late; one with no due date never is.
    register_trainer(client)
    students = client.get("/api/students").json()
    detail_keys = ("late", "on_time_rate", "assigned", "completed", "pending", "awaiting")
    if students:
        detail = client.get(f"/api/students/{students[0]['id']}").json()
        for key in detail_keys:
            assert key in detail, key


def test_student_detail_late_arithmetic(client):
    """The shape-only test above never submits anything; this exercises the
    actual computation: one exercise assigned with a due date in the past
    (submitted late), one with no due date at all (never late)."""
    register_trainer(client)
    client.cookies.clear()
    register(client, email="late@example.com")
    client.cookies.clear()
    client.post("/auth/login", json={"email": "trainer@example.com", "password": "password123"})

    sid = student_id(client, "late@example.com")
    past_due = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
    make_exercise(client, [sid], title="Late one", due=past_due)
    make_exercise(client, [sid], title="No due date", due=None)

    client.cookies.clear()
    client.post("/auth/login", json={"email": "late@example.com", "password": "password123"})
    assignments = client.get("/api/dashboard/student").json()["assignments"]
    late_assignment = next(a for a in assignments if a["title"] == "Late one")
    ontime_assignment = next(a for a in assignments if a["title"] == "No due date")
    solve(client, late_assignment["id"], "a = int(input())\nb = int(input())\nprint(a + b)")
    solve(client, ontime_assignment["id"], "a = int(input())\nb = int(input())\nprint(a + b)")

    client.cookies.clear()
    client.post("/auth/login", json={"email": "trainer@example.com", "password": "password123"})
    detail = client.get(f"/api/students/{sid}").json()

    assert detail["assigned"] == 2
    assert detail["late"] == 1
    assert detail["on_time_rate"] == 50
    assert detail["awaiting"] == 2
    assert detail["pending"] == 0
    late_row = next(e for e in detail["exercises"] if e["title"] == "Late one")
    ontime_row = next(e for e in detail["exercises"] if e["title"] == "No due date")
    assert late_row["late"] is True
    assert ontime_row["late"] is False


def test_exercise_deletion_is_reachable_from_the_detail_page(client):
    register_trainer(client)
    created = client.post("/api/exercises", json={
        "title": "Throwaway",
        "problem_statement": "x",
        "status": "published",
        "test_cases": [], "assign_to": [],
    }).json()

    page = client.get(f"/trainer/exercises/{created['id']}").text
    assert 'id="delete-exercise-btn"' in page

    assert client.delete(f"/api/exercises/{created['id']}").status_code == 200
    assert client.get(f"/api/exercises/{created['id']}").status_code == 404


def test_date_filters_restored_on_exercises_and_pending_only(client):
    register_trainer(client)
    for path in ("/trainer/exercises", "/trainer/pending"):
        html = client.get(path).text
        assert 'id="filter-from"' in html, path
        assert 'id="filter-to"' in html, path
    for path in ("/trainer/queue", "/trainer/completed"):
        html = client.get(path).text
        assert 'id="filter-from"' not in html, path
        assert 'id="filter-to"' not in html, path

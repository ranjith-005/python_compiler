"""The dashboard/exercise redesign: the requirements this pass introduced.

Grouped by the requirement each one came from, because several of them
deliberately reverse an earlier decision (activity in the nav, the exercises
dropdown, the "From your trainer" sidebar) and the reason matters when one of
these fails.
"""

from conftest import register, register_trainer
from test_dashboards import make_exercise, student_id

STUDENT = "student@example.com"


def a_class(client):
    """A trainer with one published, assigned exercise and one student."""
    register(client, STUDENT)
    client.post("/auth/logout")
    register_trainer(client)
    sid = student_id(client, STUDENT)
    make_exercise(client, [sid])
    return sid


def as_student(client):
    client.post("/auth/logout")
    client.post("/auth/login", json={"email": STUDENT, "password": "password123"})


# ── student 1: the solve page is a real coding surface ──────────────────────


def test_solve_page_mounts_monaco_over_a_textarea_fallback(client):
    sid = a_class(client)
    as_student(client)
    assignment = client.get("/api/dashboard/student").json()["assignments"][0]
    html = client.get(f"/student/assignments/{assignment['id']}/solve").text

    assert 'id="editor-host"' in html, "Monaco needs somewhere to mount"
    assert "monaco-editor" in html, "the Monaco loader should be requested"
    # The textarea stays as the value everyone reads and as the fallback when
    # Monaco cannot be fetched, so it must still be in the page.
    assert 'id="code"' in html
    # Run and Submit stay with it: writing code is only half the requirement.
    assert 'id="run-btn"' in html and 'id="output"' in html


def test_editor_falls_back_rather_than_leaving_no_input(client):
    script = open("app/static/js/code_editor.js", encoding="utf-8").read()
    assert "textareaAdapter" in script
    # mount() resolves either way; a rejected promise would leave solve.js
    # waiting forever with no editor on screen.
    assert "loadMonaco().then(" in script


# ── student 2 + 6: what the dashboard shows ─────────────────────────────────


def test_student_dashboard_carries_sessions_deadlines_and_paged_activity(client):
    register(client)
    html = client.get("/student").text
    for panel in ("Upcoming deadlines", "Upcoming sessions", "Recent activity"):
        assert panel in html, panel
    assert 'id="activity-pager"' in html
    assert "data-next" in html, "the feed needs a Next button"


def test_trainer_dashboard_carries_sessions_and_paged_activity(client):
    register_trainer(client)
    html = client.get("/trainer").text
    assert "Upcoming sessions" in html
    assert "Recent activity" in html
    assert 'id="activity-pager"' in html


# ── student 2: ten activities a page, with a total to page against ──────────


def test_activity_is_served_ten_at_a_time_with_a_total(client):
    a_class(client)
    as_student(client)

    dashboard = client.get("/api/dashboard/student").json()
    assert len(dashboard["activity"]) <= 10
    assert dashboard["activity_total"] >= 1

    page = client.get("/api/dashboard/activity").json()
    assert page["limit"] == 10 and page["offset"] == 0
    assert page["total"] == dashboard["activity_total"]
    assert [a["id"] for a in page["items"]] == [a["id"] for a in dashboard["activity"]]

    second = client.get("/api/dashboard/activity?limit=10&offset=10").json()
    assert second["offset"] == 10
    assert second["total"] == page["total"]


# ── student 3 + trainer 5: activity leaves the navigation ───────────────────


def test_neither_portal_links_activity_from_the_top_bar(client):
    register_trainer(client)
    assert 'href="/activity"' not in client.get("/trainer").text
    client.post("/auth/logout")
    register(client)
    assert 'href="/activity"' not in client.get("/student").text


# ── student 4: no trainer sidebar, no changes-requested tab ─────────────────


def test_exercises_page_drops_the_trainer_sidebar_and_the_extra_tab(client):
    register(client)
    html = client.get("/student/exercises").text
    assert "From your trainer" not in html
    assert 'data-filter="changes_requested"' not in html


# ── student 5: the trainer is named in the student's history ────────────────


def test_assigned_exercise_names_the_trainer_in_the_activity_feed(client):
    a_class(client)
    as_student(client)
    summaries = [a["summary"] for a in client.get("/api/dashboard/student").json()["activity"]]
    assert any("Trainer One" in s for s in summaries), summaries


def test_assigned_module_names_the_trainer_in_the_activity_feed(client):
    register(client, STUDENT)
    client.post("/auth/logout")
    register_trainer(client)
    sid = student_id(client, STUDENT)

    notebook = (
        b'{"cells": [{"cell_type": "markdown", "source": ["Lesson"]},'
        b' {"cell_type": "code", "source": ["print(1)"]}],'
        b' "metadata": {}, "nbformat": 4, "nbformat_minor": 5}'
    )
    created = client.post(
        "/api/modules",
        files={"file": ("lesson.ipynb", notebook, "application/json")},
        data={"title": "Loops", "description": ""},
    )
    assert created.status_code == 201, created.text
    module_id = created.json()["id"]
    assert (
        client.post(f"/api/modules/{module_id}/assign", json={"assign_to": [sid]}).status_code
        == 200
    )

    as_student(client)
    summaries = [a["summary"] for a in client.get("/api/dashboard/student").json()["activity"]]
    assert any("Trainer One" in s and "Loops" in s for s in summaries), summaries


# ── student 7: the bell carries five ────────────────────────────────────────


def test_the_bell_shows_at_most_five_notifications(client):
    register(client, STUDENT)
    client.post("/auth/logout")
    register_trainer(client)
    sid = student_id(client, STUDENT)
    for n in range(7):
        make_exercise(client, [sid], title=f"Exercise {n}")

    as_student(client)
    data = client.get("/api/dashboard/student").json()
    assert len(data["notifications"]) == 5
    # The count is of everything unread, not of the five on screen.
    assert data["unread"] == 7


# ── student 8: no changes-requested card ────────────────────────────────────


def test_the_dashboard_has_no_changes_requested_card(client):
    script = open("app/static/js/student_dashboard.js", encoding="utf-8").read()
    assert 'key: "changes_requested"' not in script


# ── trainer 2 + 3 + 6: the roster, and the cards that navigate ──────────────


def test_roster_is_a_table_without_a_score_column(client):
    register_trainer(client)
    html = client.get("/trainer/students").text
    assert "data-table" in html
    for column in ("Student", "Email", "Progress", "Status"):
        assert f">{column}<" in html, column
    # Requirement: the average tests-passed figure lives on the student's own
    # page, so the roster must not carry a second score beside it.
    assert ">Score<" not in html


def test_roster_reports_presence(client):
    a_class(client)
    students = client.get("/api/dashboard/trainer").json()["students"]
    assert students, "the roster should not be empty"
    # The trainer has just been served pages; the student has not been seen
    # since registering, but either way the field must be a real boolean.
    assert all(isinstance(s["online"], bool) for s in students)


def test_only_the_actionable_student_cards_link_anywhere(client):
    script = open("app/static/js/trainer_detail.js", encoding="utf-8").read()
    detail = script[script.index("async function studentDetail") : script.index("$(\"ex-heading\")")]
    for label in ("Assigned", "Completed", "Pending", "Awaiting review", "Late"):
        assert f'stat("{label}"' in detail, label
    # These three are figures, not destinations.
    for line in detail.splitlines():
        for label in ("On-time rate", "Avg tests passed", "Last active"):
            if f'stat("{label}"' in line:
                assert "href:" not in line, label


def test_a_student_card_filters_that_students_exercise_list(client):
    sid = a_class(client)
    html = client.get(f"/trainer/students/{sid}").text
    assert 'id="ex-heading"' in html
    script = open("app/static/js/trainer_detail.js", encoding="utf-8").read()
    assert "?view=${key}" in script
    for view in ("all", "completed", "open", "submitted", "late"):
        assert f"{view}:" in script, view


# ── trainer 4: exercises is a page with New exercise and Drafts on it ───────


def test_exercises_is_a_page_with_new_and_drafts_buttons(client):
    register_trainer(client)
    dashboard = client.get("/trainer").text
    assert 'id="ex-menu-panel"' not in dashboard, "the dropdown should be gone"
    assert 'href="/trainer/exercises"' in dashboard, "Exercises should be a plain link"

    page = client.get("/trainer/exercises").text
    new_at = page.index('href="/trainer/exercises/new"')
    drafts_at = page.index('href="/trainer/exercises/drafts"')
    # Requirement: Drafts sits to the right of New exercise, above the list.
    assert new_at < drafts_at
    assert drafts_at < page.index('id="section-list"')


# ── shared 1: the profile control shows the avatar and the name ─────────────


def test_the_profile_control_shows_an_avatar_and_the_name(client):
    register_trainer(client)
    html = client.get("/trainer").text
    assert 'class="avatar-btn"' in html
    assert 'class="avatar-name"' in html
    assert "Trainer One" in html

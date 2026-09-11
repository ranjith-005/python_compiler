"""The calendar: online sessions, personal marks, and who may see which.

Deadlines are not tested here because they are not stored here -- they are
derived from `assignments` by the dashboard that asks. What this module owns
is the distinction that decides visibility:

    'personal'  its owner's, and nobody else's, trainer or not
    'session'   a trainer scheduled it; every student sees it

That rule is enforced on read as well as on write, so the tests come in pairs:
one that the wrong person cannot create a row, one that they cannot see it.
"""

import pytest

from conftest import register, register_trainer


def make_event(client, title="Revise recursion", date="2026-10-05",
               kind="personal", description=""):
    return client.post(
        "/api/calendar",
        json={"title": title, "description": description,
              "event_date": date, "kind": kind},
    )


def titles(client):
    return [e["title"] for e in client.get("/api/calendar").json()["events"]]


# ── marking a date for yourself ────────────────────────────────────────────


def test_a_student_can_mark_a_date_for_themselves(client):
    register(client)
    created = make_event(client, "Finish the FizzBuzz exercise")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "personal"
    assert body["mine"] is True
    assert titles(client) == ["Finish the FizzBuzz exercise"]


def test_a_trainer_can_mark_a_date_for_themselves(client):
    register_trainer(client)
    assert make_event(client, "Prepare the recursion class").status_code == 201
    assert titles(client) == ["Prepare the recursion class"]


def test_a_personal_mark_carries_its_description(client):
    register(client)
    make_event(client, "Revise", description="Chapters 4 and 5 before the test")
    event = client.get("/api/calendar").json()["events"][0]
    assert event["description"] == "Chapters 4 and 5 before the test"


def test_the_date_must_be_a_real_date(client):
    register(client)
    assert make_event(client, date="not-a-date").status_code == 422
    # A day that does not exist is the case a length check alone would pass.
    assert make_event(client, date="2026-02-30").status_code == 422


def test_an_event_needs_a_title(client):
    register(client)
    assert make_event(client, title="").status_code == 422


def test_signing_out_hides_the_calendar(client):
    register(client)
    make_event(client)
    client.post("/auth/logout")
    assert client.get("/api/calendar").status_code == 401


# ── a personal mark is private ─────────────────────────────────────────────


def test_one_student_cannot_see_another_students_mark(client):
    register(client, email="first@example.com")
    make_event(client, "My own note")
    client.post("/auth/logout")

    register(client, email="second@example.com")
    assert titles(client) == []


def test_a_trainer_cannot_see_a_students_personal_mark(client):
    """Being a trainer is not a way into somebody's private notes."""
    register(client, email="student@example.com")
    make_event(client, "Something personal")
    client.post("/auth/logout")

    register_trainer(client)
    assert titles(client) == []


def test_a_student_cannot_see_a_trainers_personal_mark(client):
    register_trainer(client)
    make_event(client, "Trainer's own reminder", kind="personal")
    client.post("/auth/logout")

    register(client)
    assert titles(client) == []


# ── an online session is shared ────────────────────────────────────────────


def test_a_trainer_schedules_a_session_and_a_student_sees_it(client):
    register_trainer(client)
    scheduled = make_event(client, "Recursion live class", date="2026-10-09",
                           kind="session")
    assert scheduled.status_code == 201
    assert scheduled.json()["kind"] == "session"
    client.post("/auth/logout")

    register(client)
    events = client.get("/api/calendar").json()["events"]
    assert [e["title"] for e in events] == ["Recursion live class"]
    # Visible, but not the student's to remove.
    assert events[0]["mine"] is False


def test_the_trainer_who_scheduled_a_session_owns_it(client):
    register_trainer(client)
    make_event(client, "Recursion live class", kind="session")
    events = client.get("/api/calendar").json()["events"]
    assert events[0]["mine"] is True


def test_a_student_cannot_schedule_a_session(client):
    """Letting them would put a class on every other student's calendar."""
    register(client)
    refused = make_event(client, "Not mine to schedule", kind="session")
    assert refused.status_code == 403
    assert titles(client) == []


def test_an_unknown_kind_is_refused(client):
    register_trainer(client)
    assert make_event(client, kind="holiday").status_code == 422


# ── removing a mark ────────────────────────────────────────────────────────


def test_you_can_remove_your_own_mark(client):
    register(client)
    event_id = make_event(client).json()["id"]
    assert client.delete(f"/api/calendar/{event_id}").status_code == 200
    assert titles(client) == []


def test_you_cannot_remove_somebody_elses_mark(client):
    register(client, email="first@example.com")
    event_id = make_event(client, "Mine").json()["id"]
    client.post("/auth/logout")

    register(client, email="second@example.com")
    assert client.delete(f"/api/calendar/{event_id}").status_code == 404

    # And it is still there for the person it belongs to.
    client.post("/auth/logout")
    client.post("/auth/login",
                json={"email": "first@example.com", "password": "password123"})
    assert titles(client) == ["Mine"]


def test_a_student_cannot_remove_a_session_they_can_see(client):
    """Visibility is not ownership: a student sees the class, and that is all."""
    register_trainer(client)
    event_id = make_event(client, "Recursion live class", kind="session").json()["id"]
    client.post("/auth/logout")

    register(client)
    assert client.delete(f"/api/calendar/{event_id}").status_code == 404
    assert titles(client) == ["Recursion live class"]


def test_removing_something_that_is_not_there_is_a_404(client):
    register(client)
    assert client.delete("/api/calendar/9999").status_code == 404


# ── ordering ───────────────────────────────────────────────────────────────


def test_events_come_back_in_date_order(client):
    register(client)
    make_event(client, "Third", date="2026-12-01")
    make_event(client, "First", date="2026-10-01")
    make_event(client, "Second", date="2026-11-01")
    assert titles(client) == ["First", "Second", "Third"]

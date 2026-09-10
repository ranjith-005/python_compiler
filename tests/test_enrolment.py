"""Enrolling a student: generated credentials, and the welcome email.

Students do not sign themselves up. The trainer creates the account, hands
over the email and password, and -- because a password nobody chose is a
password nobody reuses -- the password is generated rather than typed.

Nothing here reaches a mail server. `mailer.deliver()` is the only function
that opens a socket, and these tests assert on the message it would be given.
"""

import re

import pytest

from app import mailer
from app.security import generate_password
from conftest import register, register_trainer


# ── the generated password ─────────────────────────────────────────────────


def test_a_generated_password_is_eleven_capitals_and_digits():
    for _ in range(50):
        password = generate_password()
        assert len(password) == 11
        assert re.fullmatch(r"[A-Z0-9]{11}", password), password


def test_generated_passwords_do_not_repeat():
    """A generator that returns the same value twice would hand two students
    the same credentials without anyone noticing."""
    seen = {generate_password() for _ in range(200)}
    assert len(seen) == 200


def test_a_generated_password_carries_both_kinds_of_character():
    """All-digits or all-letters is a legal draw from a naive generator and
    reads like a mistake to the student who receives it."""
    for _ in range(50):
        password = generate_password()
        assert any(c.isalpha() for c in password), password
        assert any(c.isdigit() for c in password), password


# ── the endpoint behind the Generate button ────────────────────────────────


def test_the_generate_endpoint_returns_a_usable_password(client):
    register_trainer(client)
    body = client.get("/api/students/new-password").json()
    assert re.fullmatch(r"[A-Z0-9]{11}", body["password"])


def test_a_student_cannot_generate_credentials(client):
    """The route sits under /students, which is trainer ground."""
    register(client)
    assert client.get("/api/students/new-password").status_code == 403


def test_the_generate_route_is_not_swallowed_by_the_id_route(client):
    """`/students/{student_id}` would match "new-password" as an id if it were
    declared first. main.py carries a comment about the same bug."""
    register_trainer(client)
    response = client.get("/api/students/new-password")
    assert response.status_code == 200
    assert "password" in response.json()


# ── the welcome message ────────────────────────────────────────────────────


def test_the_welcome_message_greets_the_student_by_name():
    message = mailer.welcome_message(
        name="Aditi Sharma", email="aditi@example.com",
        password="A1B2C3D4E5F", course="Python Foundations",
    )
    assert "Aditi Sharma" in message.body
    assert "Python Foundations" in message.body
    assert "Congratulations" in message.body
    assert message.to == "aditi@example.com"


def test_the_welcome_message_carries_the_credentials_to_sign_in_with():
    message = mailer.welcome_message(
        name="Aditi Sharma", email="aditi@example.com",
        password="A1B2C3D4E5F", course="Python Foundations",
    )
    assert "aditi@example.com" in message.body
    assert "A1B2C3D4E5F" in message.body


def test_a_student_with_no_name_is_greeted_by_something(client):
    """An enrolment can carry an email and nothing else; "Hello ," is worse
    than falling back to the address."""
    message = mailer.welcome_message(
        name="", email="someone@example.com", password="A1B2C3D4E5F", course="",
    )
    assert "Hello ," not in message.body
    assert "someone@example.com" in message.body


def test_the_subject_names_the_course_when_there_is_one():
    with_course = mailer.welcome_message(
        name="A", email="a@example.com", password="A1B2C3D4E5F", course="Python 101")
    without = mailer.welcome_message(
        name="A", email="a@example.com", password="A1B2C3D4E5F", course="")
    assert "Python 101" in with_course.subject
    assert without.subject


def test_a_mailto_link_is_offered_when_no_mail_server_is_configured():
    """No SMTP host is a normal state, not an error: the trainer sends it from
    their own client instead, and the credentials still reach the student."""
    message = mailer.welcome_message(
        name="Aditi", email="aditi@example.com",
        password="A1B2C3D4E5F", course="Python 101",
    )
    link = mailer.mailto_link(message)
    assert link.startswith("mailto:aditi@example.com?")
    assert "subject=" in link and "body=" in link
    # A raw newline or space in a URL is what breaks these links in practice.
    assert "\n" not in link and " " not in link


# ── enrolment end to end ───────────────────────────────────────────────────


def enrol(client, **overrides):
    body = {
        "email": "newcomer@example.com",
        "password": "A1B2C3D4E5F",
        "first_name": "New",
        "last_name": "Comer",
        "phone": "",
        "course": "Python Foundations",
        "send_welcome": True,
    }
    body.update(overrides)
    return client.post("/api/students", json=body)


def test_an_enrolled_student_can_sign_in_with_the_generated_password(client):
    """The whole point of the feature: what the trainer mails must work."""
    register_trainer(client)
    assert enrol(client).status_code == 201

    client.post("/auth/logout")
    signed_in = client.post(
        "/auth/login", json={"email": "newcomer@example.com", "password": "A1B2C3D4E5F"}
    )
    assert signed_in.status_code == 200
    assert client.get("/auth/me").json()["role"] == "student"


def test_enrolment_reports_the_welcome_it_could_not_send(client):
    """With no SMTP configured the account is still created -- the enrolment
    must not fail because the mail server is absent -- and the trainer is
    handed a mailto link instead."""
    register_trainer(client)
    body = enrol(client).json()
    assert body["welcome"]["sent"] is False
    assert body["welcome"]["mailto"].startswith("mailto:newcomer@example.com?")


def test_the_welcome_is_skipped_when_not_asked_for(client):
    register_trainer(client)
    body = enrol(client, send_welcome=False).json()
    assert body["welcome"] is None


def test_enrolling_records_it_against_the_trainer(client):
    register_trainer(client)
    enrol(client)
    summaries = [a["summary"] for a in client.get("/api/dashboard/trainer").json()["activity"]]
    assert any("New Comer" in s for s in summaries), summaries


def test_a_duplicate_email_is_refused_before_anything_is_sent(client):
    register_trainer(client)
    assert enrol(client).status_code == 201
    again = enrol(client)
    assert again.status_code == 409


def test_a_student_cannot_enrol_anybody(client):
    register(client)
    assert enrol(client).status_code == 403

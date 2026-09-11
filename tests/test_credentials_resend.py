"""Re-issuing sign-in details to a student who is already enrolled.

Enrolment already mails credentials to a new account. This is the same message
for one that exists, and it exists because what is stored is a bcrypt hash:
there is no way to re-send the password a student was given, only to issue a
new one. That makes the endpoint a password reset that happens to send mail,
which is why these tests care as much about what the old password stops doing
as about what arrives in the inbox.

Nothing here reaches a mail server. `mailer.deliver()` is the only function
that opens a socket; with none configured `send_or_link` reports `sent: False`
and returns the mailto fallback, which is the path asserted on.
"""

import pytest

from app import mailer
from conftest import register, register_trainer


def enrol(client, email="pupil@example.com", first="Meera", last="Nair"):
    password = client.get("/api/students/new-password").json()["password"]
    created = client.post(
        "/api/students",
        json={"email": email, "password": password, "first_name": first,
              "last_name": last, "phone": "", "course": "", "send_welcome": False},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"], password


def signs_in(client, email, password):
    client.post("/auth/logout")
    return client.post("/auth/login", json={"email": email, "password": password})


# ── the reset ──────────────────────────────────────────────────────────────


def test_a_trainer_issues_new_credentials_to_an_enrolled_student(client):
    register_trainer(client)
    student_id, _ = enrol(client)

    fresh = client.get("/api/students/new-password").json()["password"]
    sent = client.post(f"/api/students/{student_id}/credentials",
                       json={"password": fresh, "course": "Python Foundations"})
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert body["email"] == "pupil@example.com"
    assert body["display"] == "Meera Nair"


def test_the_new_password_works_and_the_old_one_stops(client):
    register_trainer(client)
    student_id, original = enrol(client)

    fresh = client.get("/api/students/new-password").json()["password"]
    client.post(f"/api/students/{student_id}/credentials", json={"password": fresh})

    assert signs_in(client, "pupil@example.com", original).status_code == 401
    assert signs_in(client, "pupil@example.com", fresh).status_code == 200


def test_the_address_comes_off_the_account_not_the_request(client):
    """A trainer cannot redirect one student's password to another inbox: the
    body carries no email field, so there is nothing to redirect it with."""
    register_trainer(client)
    student_id, _ = enrol(client, email="pupil@example.com")

    fresh = client.get("/api/students/new-password").json()["password"]
    sent = client.post(
        f"/api/students/{student_id}/credentials",
        json={"password": fresh, "email": "attacker@example.com"},
    )
    assert sent.status_code == 200
    assert sent.json()["email"] == "pupil@example.com"
    assert sent.json()["delivery"]["to"] == "pupil@example.com"


# ── the message ────────────────────────────────────────────────────────────


def test_the_mail_carries_the_address_and_the_new_password(client):
    register_trainer(client)
    student_id, _ = enrol(client)

    fresh = client.get("/api/students/new-password").json()["password"]
    delivery = client.post(f"/api/students/{student_id}/credentials",
                           json={"password": fresh}).json()["delivery"]

    # No mail server in the tests, so it reports the fallback rather than
    # claiming a send that never happened.
    assert delivery["sent"] is False
    assert "pupil%40example.com" in delivery["mailto"]
    assert fresh in delivery["mailto"]


def test_the_reset_message_is_not_the_welcome(client):
    """A welcome congratulates somebody on getting in, which reads badly the
    second time and worse to a student who never lost access."""
    message = mailer.credentials_message(
        name="Meera Nair", email="pupil@example.com",
        password="ABC123DEF45", course="Python Foundations",
    )
    assert "reset" in message.subject.lower()
    assert "Congratulations" not in message.body
    assert "ABC123DEF45" in message.body
    assert "pupil@example.com" in message.body
    # Somebody who did not ask for this should know who to tell.
    assert "not expecting this" in message.body


def test_the_reset_message_works_without_a_course(client):
    message = mailer.credentials_message(
        name="", email="pupil@example.com", password="ABC123DEF45", course="",
    )
    assert "pupil@example.com" in message.subject or "Python Learning Platform" in message.subject
    # With no name to greet, the address stands in rather than "Hello ,".
    assert "Hello pupil@example.com" in message.body


# ── the student is told on the platform too ────────────────────────────────


def test_the_student_is_notified_in_the_app(client):
    register_trainer(client)
    student_id, _ = enrol(client)
    fresh = client.get("/api/students/new-password").json()["password"]
    client.post(f"/api/students/{student_id}/credentials", json={"password": fresh})

    signs_in(client, "pupil@example.com", fresh)
    notifications = client.get("/api/dashboard/student").json()["notifications"]
    assert any("new password" in n["title"].lower() for n in notifications)


# ── who may do it ──────────────────────────────────────────────────────────


def test_a_student_cannot_issue_credentials(client):
    register_trainer(client)
    student_id, _ = enrol(client)
    client.post("/auth/logout")

    register(client, email="other@example.com")
    refused = client.post(f"/api/students/{student_id}/credentials",
                          json={"password": "SOMETHING123"})
    assert refused.status_code == 403


def test_a_signed_out_visitor_cannot_issue_credentials(client):
    register_trainer(client)
    student_id, _ = enrol(client)
    client.post("/auth/logout")

    refused = client.post(f"/api/students/{student_id}/credentials",
                          json={"password": "SOMETHING123"})
    assert refused.status_code == 401


def test_credentials_cannot_be_issued_to_a_trainer(client):
    """The route is for the roster. A trainer resetting another trainer's
    password would be an account takeover with an audit trail."""
    register_trainer(client)
    me = client.get("/api/dashboard/trainer")
    assert me.status_code == 200

    with_conn_id = client.post("/api/students/1/credentials",
                               json={"password": "SOMETHING123"})
    assert with_conn_id.status_code == 404


def test_an_unknown_student_is_a_404(client):
    register_trainer(client)
    refused = client.post("/api/students/9999/credentials",
                          json={"password": "SOMETHING123"})
    assert refused.status_code == 404


def test_the_password_must_be_long_enough(client):
    register_trainer(client)
    student_id, _ = enrol(client)
    assert client.post(f"/api/students/{student_id}/credentials",
                       json={"password": "short"}).status_code == 422

from conftest import register, register_trainer

from app.names import display_name


def test_display_name_prefers_full_name():
    row = {"full_name": "Nishanth Kumar", "first_name": "", "last_name": "", "email": "n@x.com"}
    assert display_name(row) == "Nishanth Kumar"


def test_display_name_falls_back_to_name_parts():
    row = {"full_name": "", "first_name": "Nishanth", "last_name": "Kumar", "email": "n@x.com"}
    assert display_name(row) == "Nishanth Kumar"


def test_display_name_prettifies_the_email_local_part():
    row = {"full_name": "", "first_name": "", "last_name": "", "email": "kuttyxkutty123@gmail.com"}
    assert display_name(row) == "Kuttyxkutty123"


def test_display_name_splits_dots_and_underscores():
    row = {"full_name": "", "first_name": "", "last_name": "", "email": "ranjith.r_iiitk@example.com"}
    assert display_name(row) == "Ranjith R Iiitk"


def test_display_name_never_returns_a_raw_email():
    row = {"full_name": "", "first_name": "", "last_name": "", "email": "someone@example.com"}
    assert "@" not in display_name(row)


def test_new_account_defaults_to_the_system_theme(client):
    register(client)
    assert client.get("/auth/me").json()["theme"] == "system"


def test_registration_leaves_the_name_empty_for_display_name_to_resolve(client):
    register(client, email="kuttyxkutty123@gmail.com")
    me = client.get("/auth/me").json()
    assert me["full_name"] == ""
    assert display_name(me) == "Kuttyxkutty123"

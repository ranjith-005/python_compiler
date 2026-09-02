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


def _change_password(client, current="password123", new="newpassword456", confirm=None):
    return client.post(
        "/auth/password",
        json={
            "current_password": current,
            "new_password": new,
            "confirm_password": new if confirm is None else confirm,
        },
    )


def test_password_change_succeeds_and_the_new_password_works(client):
    register(client)
    assert _change_password(client).status_code == 200

    client.cookies.clear()
    login = client.post(
        "/auth/login", json={"email": "user@example.com", "password": "newpassword456"}
    )
    assert login.status_code == 200


def test_password_change_reissues_the_session_cookie(client):
    register(client)
    response = _change_password(client)
    assert response.status_code == 200
    # Asserting that /auth/me still works would prove nothing: the register-time
    # cookie is still valid either way. The reissue is only observable here.
    assert "session=" in response.headers.get("set-cookie", "")


def test_password_change_keeps_the_session_alive(client):
    register(client)
    _change_password(client)
    assert client.get("/auth/me").status_code == 200


def test_password_change_rejects_a_wrong_current_password(client):
    register(client)
    response = _change_password(client, current="notmypassword")
    assert response.status_code == 400
    assert "current password" in response.json()["detail"].lower()


def test_password_change_rejects_a_mismatched_confirmation(client):
    register(client)
    response = _change_password(client, new="newpassword456", confirm="different12345")
    assert response.status_code == 400
    assert "match" in response.json()["detail"].lower()


def test_password_change_rejects_a_short_new_password(client):
    register(client)
    assert _change_password(client, new="short").status_code == 422


def test_password_change_rejects_reusing_the_current_password(client):
    register(client)
    response = _change_password(client, new="password123")
    assert response.status_code == 400
    assert "different" in response.json()["detail"].lower()


def test_password_change_requires_a_session(client):
    assert _change_password(client).status_code == 401


def test_theme_persists_to_the_account(client):
    register(client)
    response = client.patch("/api/settings/theme", json={"theme": "light"})
    assert response.status_code == 200
    assert response.json()["theme"] == "light"
    assert client.get("/auth/me").json()["theme"] == "light"


def test_theme_rejects_an_unknown_value(client):
    register(client)
    assert client.patch("/api/settings/theme", json={"theme": "sepia"}).status_code == 422


def test_theme_requires_a_session(client):
    assert client.patch("/api/settings/theme", json={"theme": "dark"}).status_code == 401


def test_profile_update_recomputes_the_full_name(client):
    register(client)
    response = client.patch(
        "/api/settings/profile",
        json={"first_name": "Nishanth", "last_name": "Kumar", "phone": "9876543210"},
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Nishanth Kumar"
    assert client.get("/auth/me").json()["full_name"] == "Nishanth Kumar"


def test_profile_update_gives_a_named_display_name(client):
    register(client)
    client.patch(
        "/api/settings/profile",
        json={"first_name": "Nishanth", "last_name": "Kumar", "phone": ""},
    )
    assert client.get("/api/settings/profile").json()["display_name"] == "Nishanth Kumar"

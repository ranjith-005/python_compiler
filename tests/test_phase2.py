from conftest import register, register_trainer


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

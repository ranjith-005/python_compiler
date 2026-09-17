from conftest import register

from app.db import get_conn, utcnow


def test_deactivated_account_loses_http_access(client):
    response = register(client)
    user_id = response.json()["id"]
    assert client.get("/auth/me").status_code == 200

    with get_conn() as conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))

    assert client.get("/auth/me").status_code == 401


def test_register_sets_session_cookie_and_welcome_notebook(client):
    response = register(client)
    assert "session" in response.cookies or "session" in client.cookies
    assert response.json()["email"] == "user@example.com"

    notebooks = client.get("/api/notebooks").json()
    assert [n["name"] for n in notebooks] == ["Welcome.ipynb"]


def test_duplicate_email_is_rejected(client):
    register(client)
    client.cookies.clear()
    response = client.post(
        "/auth/register", json={"email": "USER@example.com", "password": "password123"}
    )
    assert response.status_code == 409


def test_short_password_is_rejected(client):
    response = client.post("/auth/register", json={"email": "a@b.com", "password": "short"})
    assert response.status_code == 422


def test_invalid_email_is_rejected(client):
    response = client.post("/auth/register", json={"email": "not-an-email", "password": "password123"})
    assert response.status_code == 422


def test_login_with_correct_and_wrong_password(client):
    register(client)
    client.cookies.clear()

    bad = client.post("/auth/login", json={"email": "user@example.com", "password": "wrongpassword"})
    assert bad.status_code == 401
    assert "Incorrect email or password" in bad.json()["detail"]

    unknown = client.post("/auth/login", json={"email": "nobody@example.com", "password": "password123"})
    # Identical message: don't leak which emails exist.
    assert unknown.status_code == 401
    assert unknown.json()["detail"] == bad.json()["detail"]

    good = client.post("/auth/login", json={"email": "user@example.com", "password": "password123"})
    assert good.status_code == 200
    assert client.get("/auth/me").json()["email"] == "user@example.com"


def test_logout_clears_session(client):
    register(client)
    assert client.get("/auth/me").status_code == 200
    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401


def test_logout_records_the_real_last_seen_time(client):
    """Logout stamps users.last_seen_at so the trainer's "Last active" card
    shows the true signed-out moment, not a dummy or throttled time."""
    user_id = register(client).json()["id"]
    with get_conn() as conn:
        # Pretend the user has been idle since 2000, so whatever logout
        # writes is provably a fresh, real stamp.
        conn.execute(
            "UPDATE users SET last_seen_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (user_id,),
        )

    before = utcnow()
    assert client.post("/auth/logout").status_code == 200

    with get_conn() as conn:
        seen = conn.execute(
            "SELECT last_seen_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()["last_seen_at"]
    assert seen >= before


def test_logout_without_a_session_still_succeeds(client):
    # A stale or missing cookie must not turn the logout button into an error.
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/auth/me").status_code == 401


def test_notebook_pages_require_login(client):
    anon = client.get("/notebooks", follow_redirects=False)
    assert anon.status_code == 302
    assert anon.headers["location"] == "/login"

    register(client)
    assert client.get("/notebooks").status_code == 200
    # A logged-in user is bounced off the login page onto their own dashboard.
    logged_in = client.get("/login", follow_redirects=False)
    assert logged_in.status_code == 302
    assert logged_in.headers["location"] == "/student"


def test_root_redirects_by_session(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    register(client)
    assert client.get("/", follow_redirects=False).headers["location"] == "/student"


def test_tampered_token_is_rejected(client):
    register(client)
    client.cookies.set("session", "not.a.valid.token")
    assert client.get("/auth/me").status_code == 401

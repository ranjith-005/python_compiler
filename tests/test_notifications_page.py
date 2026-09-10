"""The notification history: every update, oldest reachable, with real times."""

from conftest import register_trainer


def _notify_many(user_id, count):
    from app.db import get_conn, notify
    with get_conn() as conn:
        for n in range(count):
            notify(conn, user_id, "assigned", f"Update {n}", "/trainer")


def test_the_history_pages_fifteen_at_a_time(client):
    register_trainer(client)
    user_id = client.get("/auth/me").json()["id"]
    _notify_many(user_id, 20)

    first = client.get("/api/dashboard/notifications").json()
    assert len(first["items"]) == 15
    assert first["total"] == 20

    second = client.get("/api/dashboard/notifications?offset=15").json()
    assert len(second["items"]) == 5


def test_every_notification_carries_its_timestamp(client):
    register_trainer(client)
    user_id = client.get("/auth/me").json()["id"]
    _notify_many(user_id, 1)
    item = client.get("/api/dashboard/notifications").json()["items"][0]
    assert item["created_at"]
    assert item["title"] == "Update 0"


def test_the_history_page_renders(client):
    register_trainer(client)
    assert client.get("/notifications").status_code == 200


def test_the_history_is_private_to_its_owner(client):
    register_trainer(client)
    owner = client.get("/auth/me").json()["id"]
    _notify_many(owner, 3)
    client.post("/auth/logout")

    from conftest import register
    register(client, email="nosy@example.com")
    assert client.get("/api/dashboard/notifications").json()["items"] == []


def test_the_history_is_ordered_by_time_not_by_unread(client):
    """The bell floats unread to the top. A history that reorders itself as
    things are read is not a history."""
    register_trainer(client)
    user_id = client.get("/auth/me").json()["id"]
    _notify_many(user_id, 3)

    client.post("/api/dashboard/notifications/read")
    from app.db import get_conn, notify
    with get_conn() as conn:
        notify(conn, user_id, "assigned", "Newest of all", "/trainer")

    titles = [n["title"] for n in client.get("/api/dashboard/notifications").json()["items"]]
    assert titles[0] == "Newest of all"
    assert titles[1:] == ["Update 2", "Update 1", "Update 0"]


def test_signing_out_hides_the_history_page(client):
    """The page carries someone's notifications, so it is not for a visitor."""
    response = client.get("/notifications", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_the_bell_offers_the_history(client):
    """The footer is the only route to the page from the chrome."""
    register_trainer(client)
    script = open("app/static/js/dashboard_common.js", encoding="utf-8").read()
    assert '"/notifications"' in script

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

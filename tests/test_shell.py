"""The sidebar shell, which every signed-in page renders through topbar()."""

from conftest import register, register_trainer


def test_the_trainer_sidebar_carries_every_nav_item(client):
    register_trainer(client)
    html = client.get("/trainer").text
    assert 'class="app-sidebar"' in html
    for label in ("Dashboard", "Exercises", "Modules", "Students", "Online session"):
        assert label in html


def test_the_student_sidebar_has_no_students_link(client):
    register(client)
    html = client.get("/student").text
    assert 'class="app-sidebar"' in html
    assert 'href="/trainer/students"' not in html


def test_the_bell_and_profile_moved_into_the_header_intact(client):
    """Their ids are the contract dashboard_common.js relies on."""
    register_trainer(client)
    html = client.get("/trainer").text
    for element_id in ("bell-btn", "bell-panel", "bell-badge", "bell-list",
                       "profile-menu", "profile-panel", "logout-btn"):
        assert f'id="{element_id}"' in html


def test_the_login_page_has_no_sidebar(client):
    """login.html does not call topbar(); the auth page must stay untouched."""
    assert 'class="app-sidebar"' not in client.get("/login").text

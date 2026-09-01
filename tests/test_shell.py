"""Phase A: the shared page shell and the trimmed dashboards.

These assert on the rendered HTML rather than on JSON, because every
requirement here is about what the page presents.
"""

from conftest import register, register_trainer

BRAND = "Python Learning Platform"


def trainer_page(client):
    register_trainer(client)
    return client.get("/trainer").text


def student_page(client):
    register(client)
    return client.get("/student").text


# ── shared requirement 2: the site is renamed ───────────────────────────────


def test_every_page_carries_the_new_brand(client):
    register_trainer(client)
    for path in ("/trainer", "/trainer/students", "/trainer/exercises", "/profile", "/activity"):
        html = client.get(path).text
        assert BRAND in html, f"{path} is missing the brand"
        assert "PyCompiler" not in html, f"{path} still says PyCompiler"


def test_student_pages_carry_the_new_brand(client):
    register(client)
    for path in ("/student", "/student/exercises", "/profile"):
        html = client.get(path).text
        assert BRAND in html, f"{path} is missing the brand"
        assert "PyCompiler" not in html, f"{path} still says PyCompiler"


def test_login_page_carries_the_new_brand(client):
    html = client.get("/login").text
    assert BRAND in html
    assert "PyCompiler" not in html


# ── requirement 1: only two stat cards ──────────────────────────────────────


def test_only_pending_and_awaiting_review_cards_remain(client):
    html = trainer_page(client)
    # The cards are built in JS, so the card set is asserted against the script.
    js = client.get("/static/js/trainer_dashboard.js").text
    cards = js[js.index("const cards = ["): js.index("const host")]
    assert "Pending submissions" in cards
    assert "Awaiting review" in cards
    for gone in ('label: "Students"', "Coding exercises", '"Completed"'):
        assert gone not in cards, f"{gone} should no longer be a card"
    assert "stat-grid" in html


# ── requirement 4: no search box in the awaiting-review panel ───────────────


def test_awaiting_review_has_no_search_box(client):
    html = trainer_page(client)
    assert 'id="review-search"' not in html


# ── requirements 5 and 11: one Students link, no duplicate shortcuts ────────


def test_a_single_students_link_and_no_duplicate_shortcuts(client):
    html = trainer_page(client)
    assert html.count('href="/trainer/students"') == 1, "expected exactly one Students link"
    head = html[html.index('class="quick"'): html.index("stat-grid")]
    assert "new-exercise-btn" in head
    assert "/trainer/queue" not in head
    assert "/trainer/exercises" not in head
    assert "/trainer/students" not in head


# ── requirements 7 and 10: deadlines lose the bar and the x/y counter ───────


def test_deadlines_have_no_progress_bar_or_counter(client):
    trainer_page(client)
    js = client.get("/static/js/trainer_dashboard.js").text
    start = js.index("function renderDeadlines")
    # Slice to the *next* section banner after the function, not the first one
    # in the file -- the header comment also mentions student progress.
    end = js.index("  // ──", start)
    block = js[start:end]
    assert block.strip(), "failed to isolate renderDeadlines"
    assert "submitted`" not in block, "the x/y submitted counter should be gone"
    assert "class: `bar" not in block, "the progress bar should be gone"


# ── requirement 9 + shared 4: avatar dropdown, options open real pages ──────


def test_profile_is_an_avatar_dropdown_on_both_portals(client):
    for html in (trainer_page(client), None):
        if html is None:
            client.post("/auth/logout")
            html = student_page(client)
        assert 'id="profile-menu"' in html
        assert "avatar" in html
        # Requirement 13: the dropdown's options navigate to full pages.
        assert 'href="/profile"' in html


# ── shared 5: activity leaves the dashboard, becomes a top button ───────────


def test_activity_is_a_top_button_not_a_dashboard_panel(client):
    html = trainer_page(client)
    assert "Recent activity" not in html, "the activity panel should be gone"
    assert 'href="/activity"' in html, "activity should be reachable from the top bar"


# ── shared 3: sections that need search have it ─────────────────────────────


def test_history_and_roster_offer_search(client):
    register_trainer(client)
    assert 'id="activity-search"' in client.get("/activity").text
    assert 'id="student-search"' in client.get("/trainer/students").text

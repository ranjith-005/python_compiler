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


# ── Phase 2 Task 5: five linked cards, replacing the old two ────────────────
# (superseded from the Phase A "only two stat cards" requirement below: the
# dashboard now links out to five pages instead of duplicating their content
# inline, so all five labels are expected here rather than excluded.)


def test_five_dashboard_cards_link_to_their_own_pages(client):
    html = trainer_page(client)
    # The cards are built in JS, so the card set is asserted against the script.
    js = client.get("/static/js/trainer_dashboard.js").text
    cards = js[js.index("const cards = ["): js.index("const host")]
    for label, href in (
        ("Students", "/trainer/students"),
        ("Pending submissions", "/trainer/pending"),
        ("Awaiting review", "/trainer/queue"),
        ("Exercises", "/trainer/exercises"),
        ("Completed", "/trainer/completed"),
    ):
        assert f'label: "{label}"' in cards, f"{label} card missing"
        assert f'href: "{href}"' in cards, f"{label} card missing its href"
    assert "stat-grid" in html


# ── requirement 4: no search box in the awaiting-review panel ───────────────


def test_awaiting_review_has_no_search_box(client):
    html = trainer_page(client)
    assert 'id="review-search"' not in html


# ── requirements 5 and 11: one Students link, no duplicate shortcuts ────────


def test_a_single_students_link_and_no_duplicate_shortcuts(client):
    html = trainer_page(client)
    assert html.count('href="/trainer/students"') == 1, "expected exactly one Students link"
    # Phase 2 Task 5 removed the quick row and the panel-grid entirely (the
    # cards render client-side, so their hrefs never land in this server HTML
    # at all); the topbar nav is the only place these shortcuts render now.
    assert 'class="quick"' not in html
    assert html.count('href="/trainer/queue"') == 0


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


# ── activity returns to the dashboard, paged, and leaves the top bar ────────
# (supersedes the earlier "activity is a top button" requirement: both
# dashboards now show the same feed ten at a time, so a second route to it in
# the navigation was redundant.)


def test_activity_is_a_paged_dashboard_panel_not_a_nav_button(client):
    for html in (trainer_page(client), None):
        if html is None:
            client.post("/auth/logout")
            html = student_page(client)
        assert "Recent activity" in html, "the dashboard should carry the activity panel"
        assert 'id="activity-pager"' in html, "the panel should page through history"
        assert 'href="/activity"' not in html, "activity should be off the top bar"


# ── shared 3: sections that need search have it ─────────────────────────────


def test_history_and_roster_offer_search(client):
    register_trainer(client)
    # /activity is no longer linked from the bar but remains the full history.
    assert 'id="activity-search"' in client.get("/activity").text
    assert 'id="student-search"' in client.get("/trainer/students").text

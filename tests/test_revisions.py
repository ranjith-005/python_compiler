"""The revision pass: hidden tests, exercise filters, queries and the module pages.

Each group names the behaviour it locks down, because several of them reverse
an earlier decision -- hidden cases used to stay hidden even when they failed,
the exercise filters used to have one tab per stored status, and answering a
query used to happen in a browser prompt.
"""

from conftest import register, register_trainer
from test_dashboards import make_exercise, student_id
from test_modules import upload

STUDENT = "rev.student@example.com"
SUM = "a = int(input())\nb = int(input())\nprint(a + b)"


def source(path):
    return open(path, encoding="utf-8").read()


def a_class(client, due=None, title="Sum of two numbers"):
    """A trainer with one published, assigned exercise and one student."""
    register(client, STUDENT)
    client.post("/auth/logout")
    register_trainer(client)
    sid = student_id(client, STUDENT)
    make_exercise(client, [sid], title=title, due=due)
    return sid


def as_student(client):
    client.post("/auth/logout")
    client.post("/auth/login", json={"email": STUDENT, "password": "password123"})


def as_trainer(client):
    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "trainer@example.com", "password": "password123"})


def only_assignment(client):
    return client.get("/api/dashboard/student").json()["assignments"][0]


# ── the editor closes for good once the trainer approves ───────────────────


def test_an_approved_exercise_can_no_longer_be_edited(client):
    a_class(client)
    as_student(client)
    assignment = only_assignment(client)
    client.post(f"/api/assignments/{assignment['id']}/open")
    client.patch(f"/api/assignments/{assignment['id']}/code", json={"code": SUM, "stdin": ""})
    client.post(f"/api/assignments/{assignment['id']}/submit")

    as_trainer(client)
    submission = client.get("/api/dashboard/trainer").json()["review_queue"][0]
    client.post(
        f"/api/submissions/{submission['id']}/review",
        json={"action": "approve", "comment": "Good."},
    )

    as_student(client)
    detail = client.get(f"/api/assignments/{assignment['id']}").json()
    assert detail["status"] == "completed"
    assert detail["locked"] is True

    # Not merely greyed out in the browser: the write itself is refused.
    edit = client.patch(
        f"/api/assignments/{assignment['id']}/code",
        json={"code": "print('changed')", "stdin": ""},
    )
    assert edit.status_code == 409
    assert client.post(f"/api/assignments/{assignment['id']}/submit").status_code == 409


def test_a_fully_passing_submit_sends_the_student_back_to_the_list(client):
    """Nothing is left to do on the solve page once every test passes."""
    script = source("app/static/js/solve.js")
    assert 'window.location.href = "/student/exercises"' in script
    assert "const allPassed = v.total > 0 && v.passed === v.total;" in script


# ── one tab per bucket, and the due date is what sorts them ────────────────


def test_unsubmitted_work_is_assigned_before_the_due_date_and_pending_after(client):
    sid = a_class(client, due="2020-01-01T09:00:00", title="Overdue one")
    as_trainer(client)
    make_exercise(client, [sid], title="In hand", due="2099-01-01T09:00:00")

    as_student(client)
    rows = {a["title"]: a for a in client.get("/api/dashboard/student").json()["assignments"]}
    assert rows["Overdue one"]["status"] == "pending"
    assert rows["In hand"]["status"] == "assigned"

    # Opening it does not move it out of the assigned bucket: only the due
    # date does that, which is what the shared filter below encodes.
    client.post(f"/api/assignments/{rows['In hand']['id']}/open")
    again = {a["title"]: a for a in client.get("/api/dashboard/student").json()["assignments"]}
    assert again["In hand"]["status"] == "in_progress"

    shared = source("app/static/js/dashboard_common.js")
    assert 'if (filter === "in_progress" || filter === "open") filter = "assigned";' in shared
    assert "function assignmentBucket(row)" in shared


def test_the_status_filters_offer_only_the_four_buckets(client):
    sid = a_class(client)
    student_detail = client.get(f"/trainer/students/{sid}").text
    assert '<option value="in_progress">' not in student_detail
    for value in ("all", "assigned", "pending", "submitted", "completed"):
        assert f'<option value="{value}">' in student_detail, value

    as_student(client)
    exercises = client.get("/student/exercises").text
    assert 'data-filter="in_progress"' not in exercises
    assert 'data-filter="all"' not in exercises
    # The page opens on the work still in hand.
    assert '<button class="active" data-filter="assigned">' in exercises


# ── answering a query happens on the page, not in a browser prompt ─────────


def test_granting_access_is_written_in_a_section_not_a_prompt(client):
    for path in ("app/static/js/trainer_section.js", "app/static/js/trainer_detail.js"):
        script = source(path)
        # The comment above the replacement still names the prompt it replaced,
        # so this looks for the call, not the word.
        assert "window.prompt(" not in script, path
        assert "query-decision" in script, path
        assert "decision-input" in script, path
    # The section is appended under the query it answers.
    assert "decision-slot" in source("app/static/js/trainer_section.js")


def test_a_granted_query_still_reopens_only_that_students_exercise(client):
    a_class(client, due="2020-01-01T09:00:00")
    as_student(client)
    assignment = only_assignment(client)
    raised = client.post(
        f"/api/assignments/{assignment['id']}/access-request",
        json={"message": "Please reopen it."},
    )
    assert raised.status_code == 201
    assert client.get(f"/api/assignments/{assignment['id']}").json()["locked"] is True

    as_trainer(client)
    request = client.get("/api/access-requests").json()[0]
    assert request["status"] == "pending"
    decided = client.post(
        f"/api/access-requests/{request['id']}/decide",
        json={"action": "approve", "message": "Until Friday."},
    )
    assert decided.status_code == 200

    as_student(client)
    assert client.get(f"/api/assignments/{assignment['id']}").json()["locked"] is False


# ── recent activity filters on what happened, not on a word in the text ────


def test_the_activity_feed_filters_by_category(client):
    a_class(client)
    as_trainer(client)
    upload(client)

    feed = client.get("/api/dashboard/activity?limit=50").json()
    assert feed["category"] == "all"

    exercises = client.get("/api/dashboard/activity?limit=50&category=exercise").json()
    modules = client.get("/api/dashboard/activity?limit=50&category=module").json()

    assert exercises["items"], "creating an exercise is exercise activity"
    assert modules["items"], "uploading a module is module activity"
    assert all(a["category"] == "exercise" for a in exercises["items"])
    assert all(a["category"] == "module" for a in modules["items"])
    # The total travels with the filter, so the pager counts the filtered feed.
    assert exercises["total"] == len(exercises["items"])
    assert modules["total"] == len(modules["items"])
    assert feed["total"] == len(feed["items"])
    assert exercises["total"] + modules["total"] <= feed["total"]


def test_a_submission_is_submission_activity_on_both_sides(client):
    a_class(client)
    as_student(client)
    assignment = only_assignment(client)
    client.post(f"/api/assignments/{assignment['id']}/open")
    client.patch(f"/api/assignments/{assignment['id']}/code", json={"code": SUM, "stdin": ""})
    client.post(f"/api/assignments/{assignment['id']}/submit")

    mine = client.get("/api/dashboard/activity?limit=50&category=submission").json()["items"]
    assert any("Submitted" in a["summary"] for a in mine)

    as_trainer(client)
    theirs = client.get("/api/dashboard/activity?limit=50&category=submission").json()["items"]
    assert any("submitted" in a["summary"] for a in theirs)
    # And the same event is not counted as exercise activity as well.
    exercise_feed = client.get("/api/dashboard/activity?limit=50&category=exercise").json()
    assert all("tests passed" not in a["summary"] for a in exercise_feed["items"])


def test_an_unknown_category_falls_back_to_everything(client):
    a_class(client)
    as_trainer(client)
    everything = client.get("/api/dashboard/activity?limit=50").json()
    nonsense = client.get("/api/dashboard/activity?limit=50&category=nonsense").json()
    assert nonsense["category"] == "all"
    assert nonsense["total"] == everything["total"]


# ── one back control, on every page ───────────────────────────────────────


def test_every_signed_in_page_carries_a_back_control(client):
    sid = a_class(client)
    for path in ("/trainer", "/trainer/exercises", "/trainer/modules",
                 f"/trainer/students/{sid}", "/activity", "/settings"):
        html = client.get(path).text
        assert 'id="nav-back"' in html, path
        assert "sessionStorage.getItem(KEY)" in html, path

    as_student(client)
    for path in ("/student", "/student/exercises", "/student/modules"):
        assert 'id="nav-back"' in client.get(path).text, path


def test_the_back_control_walks_the_pages_visited_not_the_url_bar(client):
    """It reads a trail kept in sessionStorage, because several pages are
    reached through a redirect that a single history step lands back on."""
    register_trainer(client)
    html = client.get("/trainer").text
    assert '"nav:history"' in html
    # Arriving by pressing Back pops the page just left, so the trail does not
    # grow by one on every step backwards.
    assert "stack.pop();" in html


# ── the trainer reads a module the way the student does ───────────────────


def test_the_trainer_module_sections_are_not_boxed_in_a_panel(client):
    register_trainer(client)
    job = upload(client)
    html = client.get(f"/trainer/modules/{job['module_id']}").text

    anchor = html.index('id="b-list"')
    assert 'class="panel"' not in html[anchor - 400:anchor], (
        "the sections list should not sit in a panel box"
    )
    assert 'class="sections-head"' in html
    # The rule between sections is the class the student's player uses too.
    assert "section-panel" in source("app/static/js/modules.js")


def test_a_student_module_shows_its_progress_as_a_percentage(client):
    script = source("app/static/js/modules.js")
    assert 'class: "bar-percent" }, `${m.progress}%`' in script
    assert ".bar-percent" in source("app/static/css/dashboard.css")

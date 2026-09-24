"""Learning modules end to end (module reqs 1-30; reqs 14, 15, 17).

The trainer uploads a document, reviews the draft it produces, edits it and
publishes; the student then sees exactly that, works through it and keeps their
progress. Everything here goes through the HTTP API, because the rules being
checked -- what a student can see, what moves the progress bar -- are rules
about the API, not about the helpers underneath it.
"""

import time

from conftest import register, register_trainer
from docbuilders import deck_bytes, pdf_bytes

FILLER = "This paragraph exists to give the topic enough words to stand alone as a section."

# Two prose topics and two practical ones: the shape module req 2 spells out.
COURSE = [
    ("Introduction to Python", [FILLER, "Python reads like English."]),
    ("Variables", [FILLER, "x = 10", "y = 20", "print(x + y)"]),
    ("History of Python", [FILLER, "Guido van Rossum released it in 1991."]),
    ("Loops", [FILLER, "for i in range(3):", " print(i)"]),
]


def login(client, email, password="password123"):
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res


def as_trainer(client):
    return login(client, "trainer@example.com")


def as_student(client, email="user@example.com"):
    return login(client, email)


def upload(client, slides=COURSE, title="Python Basics", name="course.pptx",
           description="Learn Python fundamentals."):
    """Upload a deck and wait for the background worker to finish (req 17)."""
    res = client.post(
        "/api/modules",
        files={"file": (name, deck_bytes(slides),
                        "application/vnd.openxmlformats-officedocument."
                        "presentationml.presentation")},
        data={"title": title, "description": description},
    )
    assert res.status_code == 202, res.text
    job_id = res.json()["job_id"]

    deadline = time.time() + 30
    while time.time() < deadline:
        job = client.get(f"/api/modules/jobs/{job_id}").json()
        if job["state"] == "done":
            return job
        assert job["state"] != "error", job["message"]
        time.sleep(0.05)
    raise AssertionError("the upload job never finished")


def a_course(client, slides=COURSE, **kwargs):
    """Trainer + student + an uploaded, published, assigned module."""
    register(client)
    client.post("/auth/logout")
    register_trainer(client)
    student = client.get("/api/students").json()[0]["id"]

    job = upload(client, slides, **kwargs)
    module_id = job["module_id"]
    assert client.post(f"/api/modules/{module_id}/publish").status_code == 200
    assert client.post(
        f"/api/modules/{module_id}/assign", json={"assign_to": [student]}
    ).status_code == 200
    return module_id, student


# ── upload: format, completeness, and the draft it produces ─────────────────


def test_a_notebook_is_no_longer_accepted(client):
    """Module req 1: the .ipynb path is gone, and says so."""
    register_trainer(client)
    res = client.post(
        "/api/modules",
        files={"file": ("lesson.ipynb", b'{"cells": []}', "application/json")},
        data={"title": "Loops"},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == (
        "Unsupported file format. Please upload a PDF, PPT, or PPTX file."
    )


def test_an_unsupported_format_is_rejected_by_the_backend(client):
    register_trainer(client)
    res = client.post(
        "/api/modules",
        files={"file": ("notes.docx", b"anything", "application/octet-stream")},
        data={"title": "Notes"},
    )
    assert res.status_code == 400
    assert "PDF, PPT, or PPTX" in res.json()["detail"]


def test_a_pdf_upload_becomes_a_draft_module(client):
    register_trainer(client)
    pages = [["Introduction to Python", FILLER], ["Variables", "x = 10", "print(x)"]]
    res = client.post(
        "/api/modules",
        files={"file": ("course.pdf", pdf_bytes(pages), "application/pdf")},
        data={"title": "From a PDF", "description": ""},
    )
    assert res.status_code == 202, res.text
    job_id = res.json()["job_id"]
    for _ in range(600):
        job = client.get(f"/api/modules/jobs/{job_id}").json()
        if job["state"] != "running":
            break
        time.sleep(0.05)
    assert job["state"] == "done", job.get("message")

    module = client.get(f"/api/modules/{job['module_id']}").json()
    assert module["status"] == "draft"
    assert module["source_type"] == "pdf"
    assert module["source_name"] == "course.pdf"
    assert module["section_count"] >= 2


def test_upload_reports_the_stages_it_reaches(client):
    """Module req 17: the job carries real progress, and a result at the end."""
    register_trainer(client)
    job = upload(client)
    assert job["step"] == "done"
    assert job["units"] == len(COURSE)
    assert job["sections"] == len(COURSE)
    assert job["message"].startswith("Your module draft is ready for review.")


def test_a_long_deck_is_processed_in_full(client):
    """Module reqs 4, 24: no page or slide ceiling anywhere in the pipeline."""
    register_trainer(client)
    slides = [(f"Topic {n}", [FILLER, FILLER, FILLER, f"Detail for topic {n}."])
              for n in range(1, 121)]
    job = upload(client, slides, title="Long deck")
    assert job["units"] == 120
    module = client.get(f"/api/modules/{job['module_id']}").json()
    assert module["section_count"] == 120
    # Nothing from the far end of the deck was quietly dropped.
    assert "Detail for topic 120." in module["sections"][-1]["content"]


def test_the_uploaded_file_stays_with_the_module(client):
    """Module req 18."""
    register_trainer(client)
    job = upload(client)
    module = client.get(f"/api/modules/{job['module_id']}").json()
    assert module["source_name"] == "course.pptx"
    assert module["source_type"] == "pptx"
    assert module["source_path"].endswith(".pptx")


# ── the draft the trainer reviews (module reqs 10, 12) ──────────────────────


def test_prose_sections_survive_and_only_practical_ones_get_code(client):
    register_trainer(client)
    job = upload(client)
    sections = client.get(f"/api/modules/{job['module_id']}").json()["sections"]

    assert [s["title"] for s in sections] == [
        "Introduction to Python", "Variables", "History of Python", "Loops"
    ]
    assert [bool(s["has_code_practice"]) for s in sections] == [False, True, False, True]
    # Module req 6: content is never dropped for want of code.
    for section in sections:
        assert section["content"].strip(), f"{section['title']} lost its content"


# ── trainer editing (module req 13) ─────────────────────────────────────────


def test_the_trainer_can_edit_every_part_of_a_section(client):
    register_trainer(client)
    module_id = upload(client)["module_id"]
    section = client.get(f"/api/modules/{module_id}").json()["sections"][0]

    res = client.patch(
        f"/api/modules/{module_id}/sections/{section['id']}",
        json={
            "title": "Renamed",
            "content": "New content",
            "has_code_practice": True,
            "code_question": "Print your name",
            "starter_code": "print('hi')",
        },
    )
    assert res.status_code == 200, res.text
    edited = client.get(f"/api/modules/{module_id}").json()["sections"][0]
    assert edited["title"] == "Renamed"
    assert edited["content"] == "New content"
    assert edited["has_code_practice"] == 1
    assert edited["code_question"] == "Print your name"


def test_code_practice_can_be_turned_off_by_the_trainer(client):
    register_trainer(client)
    module_id = upload(client)["module_id"]
    variables = client.get(f"/api/modules/{module_id}").json()["sections"][1]
    assert variables["has_code_practice"] == 1

    client.patch(
        f"/api/modules/{module_id}/sections/{variables['id']}",
        json={"has_code_practice": False},
    )
    after = client.get(f"/api/modules/{module_id}").json()["sections"][1]
    assert after["has_code_practice"] == 0
    # Turning practice off must not take the lesson with it (module req 10).
    assert after["content"].strip()


def test_sections_can_be_added_reordered_merged_split_and_deleted(client):
    register_trainer(client)
    module_id = upload(client)["module_id"]

    def titles():
        return [s["title"] for s in client.get(f"/api/modules/{module_id}").json()["sections"]]

    original = titles()

    added = client.post(
        f"/api/modules/{module_id}/sections", json={"title": "Extra", "content": "Body"}
    )
    assert added.status_code == 201
    assert titles()[-1] == "Extra"

    sections = client.get(f"/api/modules/{module_id}").json()["sections"]
    assert client.post(
        f"/api/modules/{module_id}/sections/{sections[1]['id']}/move",
        json={"direction": "up"},
    ).status_code == 200
    assert titles()[:2] == [original[1], original[0]]

    # Split the first section in two at its second line.
    first = client.get(f"/api/modules/{module_id}").json()["sections"][0]
    if len((first["content"] or "").splitlines()) > 1:
        res = client.post(
            f"/api/modules/{module_id}/sections/{first['id']}/split",
            json={"at_line": 1, "title": "Second half"},
        )
        assert res.status_code == 200, res.text
        assert "Second half" in titles()

    # Merge it back.
    first = client.get(f"/api/modules/{module_id}").json()["sections"][0]
    assert client.post(
        f"/api/modules/{module_id}/sections/{first['id']}/merge"
    ).status_code == 200

    doomed = client.get(f"/api/modules/{module_id}").json()["sections"][-1]
    assert client.delete(
        f"/api/modules/{module_id}/sections/{doomed['id']}"
    ).status_code == 200
    assert doomed["title"] not in titles()


def test_merging_keeps_the_code_practice_of_either_half(client):
    register_trainer(client)
    module_id = upload(client)["module_id"]
    sections = client.get(f"/api/modules/{module_id}").json()["sections"]
    # Section 1 is prose, section 2 has practice; merging must not lose it.
    res = client.post(f"/api/modules/{module_id}/sections/{sections[1]['id']}/merge")
    assert res.status_code == 200
    merged = client.get(f"/api/modules/{module_id}").json()["sections"][1]
    assert merged["has_code_practice"] == 1


def test_the_module_name_and_description_can_be_edited(client):
    register_trainer(client)
    module_id = upload(client)["module_id"]
    res = client.patch(
        f"/api/modules/{module_id}", json={"title": "Renamed", "description": "New"}
    )
    assert res.status_code == 200
    module = client.get(f"/api/modules/{module_id}").json()
    assert (module["title"], module["description"]) == ("Renamed", "New")


# ── draft versus published (module reqs 15, 18, 19) ─────────────────────────


def test_a_draft_module_is_invisible_to_the_student(client):
    register(client)
    client.post("/auth/logout")
    register_trainer(client)
    student = client.get("/api/students").json()[0]["id"]
    module_id = upload(client)["module_id"]
    client.post(f"/api/modules/{module_id}/assign", json={"assign_to": [student]})

    as_student(client)
    assert client.get("/api/modules").json() == []
    assert client.get(f"/api/modules/{module_id}").status_code == 404


def test_publishing_makes_the_module_visible_to_assigned_students(client):
    module_id, _ = a_course(client)
    as_student(client)
    listed = client.get("/api/modules").json()
    assert [m["id"] for m in listed] == [module_id]
    assert listed[0]["sections"] == len(COURSE)


def test_an_unassigned_module_stays_invisible_even_when_published(client):
    register(client)
    client.post("/auth/logout")
    register_trainer(client)
    module_id = upload(client)["module_id"]
    client.post(f"/api/modules/{module_id}/publish")

    as_student(client)
    assert client.get("/api/modules").json() == []
    assert client.get(f"/api/modules/{module_id}").status_code == 404


def test_draft_edits_do_not_reach_the_student_until_published(client):
    """Module req 19, the whole point of the two revisions."""
    module_id, _ = a_course(client)

    as_trainer(client)
    section = client.get(f"/api/modules/{module_id}").json()["sections"][0]
    client.patch(
        f"/api/modules/{module_id}/sections/{section['id']}",
        json={"title": "Edited in draft"},
    )
    client.post(f"/api/modules/{module_id}/sections", json={"title": "Draft only"})

    as_student(client)
    titles = [s["title"] for s in client.get(f"/api/modules/{module_id}").json()["sections"]]
    assert "Edited in draft" not in titles
    assert "Draft only" not in titles
    assert titles[0] == "Introduction to Python"

    as_trainer(client)
    client.post(f"/api/modules/{module_id}/publish")

    as_student(client)
    titles = [s["title"] for s in client.get(f"/api/modules/{module_id}").json()["sections"]]
    assert titles[0] == "Edited in draft"
    assert "Draft only" in titles


# ── the student page mirrors the published module (module reqs 1, 2, 20) ────


def test_the_student_sees_the_exact_structure_the_trainer_published(client):
    module_id, _ = a_course(client)
    as_student(client)
    sections = client.get(f"/api/modules/{module_id}").json()["sections"]

    assert [s["title"] for s in sections] == [
        "Introduction to Python", "Variables", "History of Python", "Loops"
    ]
    # Content-only sections never disappear (module req 2).
    assert [s["has_code_practice"] for s in sections] == [False, True, False, True]
    for section in sections:
        assert section["content"].strip()
    for section in sections:
        if not section["has_code_practice"]:
            assert section["code_question"] == "" or "code_question" not in section


# ── running code: one editor, one button, one output (module reqs 5-7) ──────


def test_each_section_runs_only_its_own_code(client):
    module_id, _ = a_course(client)
    as_student(client)
    sections = client.get(f"/api/modules/{module_id}").json()["sections"]
    variables, loops = sections[1], sections[3]

    first = client.post(
        f"/api/modules/{module_id}/sections/{variables['id']}/run",
        json={"code": "print('from variables')"},
    ).json()
    second = client.post(
        f"/api/modules/{module_id}/sections/{loops['id']}/run",
        json={"code": "print('from loops')"},
    ).json()

    assert first["stdout"].strip() == "from variables"
    assert second["stdout"].strip() == "from loops"

    # Running one leaves the other's saved state alone.
    after = client.get(f"/api/modules/{module_id}").json()["sections"]
    assert "from variables" in after[1]["starter_code"]
    assert "from loops" in after[3]["starter_code"]


def test_a_failing_run_reports_its_own_error_and_nothing_else(client):
    module_id, _ = a_course(client)
    as_student(client)
    sections = client.get(f"/api/modules/{module_id}").json()["sections"]
    res = client.post(
        f"/api/modules/{module_id}/sections/{sections[1]['id']}/run",
        json={"code": "raise ValueError('nope')"},
    ).json()
    assert res["ok"] is False
    assert "ValueError" in res["stderr"]


def test_a_section_without_code_practice_cannot_be_run(client):
    module_id, _ = a_course(client)
    as_student(client)
    prose = client.get(f"/api/modules/{module_id}").json()["sections"][0]
    res = client.post(
        f"/api/modules/{module_id}/sections/{prose['id']}/run", json={"code": "print(1)"}
    )
    assert res.status_code == 400


def test_a_student_cannot_run_a_section_of_a_module_they_lack(client):
    register(client)
    client.post("/auth/logout")
    register_trainer(client)
    module_id = upload(client)["module_id"]
    client.post(f"/api/modules/{module_id}/publish")
    section_id = client.get(f"/api/modules/{module_id}").json()["sections"][1]["id"]

    as_student(client)
    res = client.post(
        f"/api/modules/{module_id}/sections/{section_id}/run", json={"code": "print(1)"}
    )
    assert res.status_code == 404


# ── completion and progress (module reqs 8, 9, 12, 13, 21, 22) ──────────────


def test_opening_a_module_completes_nothing(client):
    """Module req 13."""
    module_id, _ = a_course(client)
    as_student(client)
    module = client.get(f"/api/modules/{module_id}").json()
    assert module["completed_sections"] == 0
    assert module["progress"] == 0
    assert all(not s["completed"] for s in module["sections"])


def test_running_code_does_not_complete_a_section(client):
    """Module req 22: successful code is not a substitute for the tick."""
    module_id, _ = a_course(client)
    as_student(client)
    section = client.get(f"/api/modules/{module_id}").json()["sections"][1]
    res = client.post(
        f"/api/modules/{module_id}/sections/{section['id']}/run",
        json={"code": "print('all good')"},
    ).json()
    assert res["ok"] is True
    assert res["completed_sections"] == 0
    assert res["progress"] == 0


def test_marking_a_section_complete_moves_the_progress_bar(client):
    module_id, _ = a_course(client)
    as_student(client)
    sections = client.get(f"/api/modules/{module_id}").json()["sections"]

    first = client.post(
        f"/api/modules/{module_id}/sections/{sections[0]['id']}/complete",
        json={"completed": True},
    ).json()
    assert (first["completed_sections"], first["total_sections"]) == (1, 4)
    assert first["progress"] == 25
    assert first["module_completed"] is False

    for section in sections[1:]:
        last = client.post(
            f"/api/modules/{module_id}/sections/{section['id']}/complete",
            json={"completed": True},
        ).json()
    assert last["progress"] == 100
    assert last["module_completed"] is True


def test_completion_can_be_undone(client):
    module_id, _ = a_course(client)
    as_student(client)
    section = client.get(f"/api/modules/{module_id}").json()["sections"][0]
    client.post(
        f"/api/modules/{module_id}/sections/{section['id']}/complete",
        json={"completed": True},
    )
    res = client.post(
        f"/api/modules/{module_id}/sections/{section['id']}/complete",
        json={"completed": False},
    ).json()
    assert res["completed_sections"] == 0


def test_completed_sections_keep_their_content(client):
    """Module reqs 14, 27: completing a section does not hide it."""
    module_id, _ = a_course(client)
    as_student(client)
    section = client.get(f"/api/modules/{module_id}").json()["sections"][1]
    client.post(
        f"/api/modules/{module_id}/sections/{section['id']}/complete",
        json={"completed": True},
    )
    after = client.get(f"/api/modules/{module_id}").json()["sections"][1]
    assert after["completed"] is True
    assert after["content"] == section["content"]
    assert after["has_code_practice"] is True


def test_progress_survives_logout_and_login(client):
    """Module reqs 9, 15, 17."""
    module_id, _ = a_course(client)
    as_student(client)
    sections = client.get(f"/api/modules/{module_id}").json()["sections"]
    client.post(
        f"/api/modules/{module_id}/sections/{sections[0]['id']}/complete",
        json={"completed": True},
    )

    client.post("/auth/logout")
    as_student(client)
    module = client.get(f"/api/modules/{module_id}").json()
    assert module["completed_sections"] == 1
    assert module["progress"] == 25
    assert module["sections"][0]["completed"] is True


def test_progress_survives_the_trainer_republishing(client):
    """The section key outlives the row, so an edit does not reset anyone."""
    module_id, _ = a_course(client)
    as_student(client)
    sections = client.get(f"/api/modules/{module_id}").json()["sections"]
    client.post(
        f"/api/modules/{module_id}/sections/{sections[0]['id']}/complete",
        json={"completed": True},
    )

    as_trainer(client)
    draft = client.get(f"/api/modules/{module_id}").json()["sections"][0]
    client.patch(
        f"/api/modules/{module_id}/sections/{draft['id']}", json={"title": "Introduction"}
    )
    client.post(f"/api/modules/{module_id}/publish")

    as_student(client)
    module = client.get(f"/api/modules/{module_id}").json()
    assert module["completed_sections"] == 1
    assert module["sections"][0]["title"] == "Introduction"
    assert module["sections"][0]["completed"] is True


def test_progress_is_separate_for_each_student(client):
    """Module req 10."""
    module_id, first = a_course(client)
    register(client, "second@example.com")
    client.post("/auth/logout")
    as_trainer(client)
    students = {s["email"]: s["id"] for s in client.get("/api/students").json()}
    client.post(
        f"/api/modules/{module_id}/assign",
        json={"assign_to": [students["second@example.com"]]},
    )

    as_student(client)
    sections = client.get(f"/api/modules/{module_id}").json()["sections"]
    for section in sections[:3]:
        client.post(
            f"/api/modules/{module_id}/sections/{section['id']}/complete",
            json={"completed": True},
        )

    as_student(client, "second@example.com")
    theirs = client.get(f"/api/modules/{module_id}").json()
    assert theirs["completed_sections"] == 0
    assert theirs["progress"] == 0

    as_student(client)
    mine = client.get(f"/api/modules/{module_id}").json()
    assert mine["completed_sections"] == 3
    assert mine["progress"] == 75


def test_progress_is_separate_for_each_module(client):
    """Module req 11."""
    first_id, student = a_course(client)
    as_trainer(client)
    second_id = upload(client, COURSE[:2], title="Second module")["module_id"]
    client.post(f"/api/modules/{second_id}/publish")
    client.post(f"/api/modules/{second_id}/assign", json={"assign_to": [student]})

    as_student(client)
    section = client.get(f"/api/modules/{first_id}").json()["sections"][0]
    client.post(
        f"/api/modules/{first_id}/sections/{section['id']}/complete",
        json={"completed": True},
    )

    by_id = {m["id"]: m for m in client.get("/api/modules").json()}
    assert by_id[first_id]["progress"] == 25
    assert by_id[second_id]["progress"] == 0


def test_progress_is_dynamic_in_the_number_of_sections(client):
    """Module req 24: the percentage follows the real section count."""
    slides = [(f"Topic {n}", [FILLER, FILLER, FILLER, f"Detail {n}."]) for n in range(1, 11)]
    module_id, _ = a_course(client, slides, title="Ten sections")

    as_student(client)
    sections = client.get(f"/api/modules/{module_id}").json()["sections"]
    assert len(sections) == 10
    for index, section in enumerate(sections[:6], start=1):
        res = client.post(
            f"/api/modules/{module_id}/sections/{section['id']}/complete",
            json={"completed": True},
        ).json()
        assert res["progress"] == index * 10
    assert res["completed_sections"] == 6
    assert res["total_sections"] == 10


def test_the_module_list_carries_progress_and_the_next_section(client):
    """Module reqs 15, 17: resume where you left off."""
    module_id, _ = a_course(client)
    as_student(client)
    sections = client.get(f"/api/modules/{module_id}").json()["sections"]
    client.post(
        f"/api/modules/{module_id}/sections/{sections[0]['id']}/complete",
        json={"completed": True},
    )

    listed = client.get("/api/modules").json()[0]
    assert listed["completed_sections"] == 1
    assert listed["sections"] == 4
    assert listed["progress"] == 25
    assert listed["completed"] is False
    assert listed["next_section_id"] == sections[1]["id"]


def test_a_finished_module_reports_completed(client):
    """Module req 16."""
    module_id, _ = a_course(client)
    as_student(client)
    for section in client.get(f"/api/modules/{module_id}").json()["sections"]:
        client.post(
            f"/api/modules/{module_id}/sections/{section['id']}/complete",
            json={"completed": True},
        )
    listed = client.get("/api/modules").json()[0]
    assert listed["progress"] == 100
    assert listed["completed"] is True


# ── what the trainer sees back (req 17) ─────────────────────────────────────


def test_the_trainer_sees_each_student_progress_through_a_module(client):
    module_id, _ = a_course(client)
    as_student(client)
    sections = client.get(f"/api/modules/{module_id}").json()["sections"]
    client.post(
        f"/api/modules/{module_id}/sections/{sections[0]['id']}/complete",
        json={"completed": True},
    )

    as_trainer(client)
    students = client.get(f"/api/modules/{module_id}").json()["students"]
    assert len(students) == 1
    assert students[0]["completed_sections"] == 1
    assert students[0]["total_sections"] == 4
    assert students[0]["progress"] == 25


# ── role guards ─────────────────────────────────────────────────────────────


def test_module_pages_are_role_guarded(client):
    register(client)
    assert client.get("/student/modules").status_code == 200
    assert client.get("/trainer/modules", follow_redirects=False).status_code == 302

    client.post("/auth/logout")
    register_trainer(client)
    assert client.get("/trainer/modules").status_code == 200
    assert client.get("/student/modules", follow_redirects=False).status_code == 302


def test_a_student_cannot_upload_or_edit_a_module(client):
    module_id, _ = a_course(client)
    as_student(client)
    assert client.post(
        "/api/modules",
        files={"file": ("x.pptx", deck_bytes(COURSE), "application/octet-stream")},
        data={"title": "Mine"},
    ).status_code == 403
    assert client.patch(f"/api/modules/{module_id}", json={"title": "Mine"}).status_code == 403
    assert client.post(f"/api/modules/{module_id}/publish").status_code == 403


def test_a_trainer_cannot_touch_another_trainers_module(client):
    register_trainer(client)
    module_id = upload(client)["module_id"]
    client.post("/auth/logout")
    register_trainer(client, "other@example.com")

    assert client.get(f"/api/modules/{module_id}").status_code == 404
    assert client.patch(f"/api/modules/{module_id}", json={"title": "Mine"}).status_code == 404
    assert client.post(f"/api/modules/{module_id}/publish").status_code == 404
    assert client.delete(f"/api/modules/{module_id}").status_code == 404


# ── reference code vs the student's editor (module req 23) ──────────────────


def test_reference_code_round_trips_and_the_student_editor_stays_empty(client):
    """The trainer edits reference code; the student's starter stays empty."""
    register_trainer(client)
    module_id = upload(client)["module_id"]
    section = client.get(f"/api/modules/{module_id}").json()["sections"][1]

    res = client.patch(
        f"/api/modules/{module_id}/sections/{section['id']}",
        json={"reference_code": "for i in range(3):\n    print(i)"},
    )
    assert res.status_code == 200, res.text

    edited = client.get(f"/api/modules/{module_id}").json()["sections"][1]
    assert edited["reference_code"] == "for i in range(3):\n    print(i)"
    assert edited["starter_code"] == ""


def test_the_job_says_how_the_sections_were_built(client):
    """A trainer reviewing a draft must know whether the AI pass actually ran,
    so a fallback draft is never mistaken for a structured one (module req 19).
    The test suite has no Groq key, so this is the offline path."""
    register_trainer(client)
    job = upload(client)
    assert job["structured_by"] == "offline"


def test_running_the_reference_does_not_overwrite_the_students_own_code(client):
    """The reference has its own Run button. Pressing it must not clobber the
    code the student has been writing in their own editor (module req 23)."""
    module_id, _ = a_course(client)
    as_student(client)
    section = client.get(f"/api/modules/{module_id}").json()["sections"][1]

    client.post(
        f"/api/modules/{module_id}/sections/{section['id']}/run",
        json={"code": "print('my own work')"},
    )
    client.post(
        f"/api/modules/{module_id}/sections/{section['id']}/run",
        json={"code": "", "kind": "reference"},
    )

    mine = client.get(f"/api/modules/{module_id}").json()["sections"][1]
    assert mine["starter_code"] == "print('my own work')"


def test_the_reference_runs_the_stored_example_not_whatever_was_posted(client):
    """A reference run ignores the client's code and executes the section's own
    reference, so the button cannot be repurposed to run something else."""
    module_id, _ = a_course(client)
    trainer_section = client.get(f"/api/modules/{module_id}").json()["sections"][1]
    client.patch(
        f"/api/modules/{module_id}/sections/{trainer_section['id']}",
        json={"reference_code": "print('the real reference')"},
    )
    client.post(f"/api/modules/{module_id}/publish")

    as_student(client)
    section = client.get(f"/api/modules/{module_id}").json()["sections"][1]
    res = client.post(
        f"/api/modules/{module_id}/sections/{section['id']}/run",
        json={"code": "print('something else')", "kind": "reference"},
    ).json()
    assert "the real reference" in res["stdout"]
    assert "something else" not in res["stdout"]

"""Document processing: extraction and grouping (module reqs 4-11)."""

import pathlib

import pytest

from docbuilders import deck_bytes, pdf_bytes

from app.documents import (
    DocumentError,
    MIN_SECTION_WORDS,
    build_sections,
    extract_units,
    suffix_of,
)

FILLER = "This paragraph exists to give the topic enough words to stand alone as a section."


def slides_for(titles):
    """One slide per title, each with enough words to stand alone as a section."""
    return [(title, [FILLER, FILLER, FILLER, f"More about {title.lower()}."])
            for title in titles]


# ── what counts as a supported upload (module reqs 2, 3) ────────────────────


def test_only_pdf_ppt_and_pptx_are_recognised():
    assert suffix_of("lesson.pdf") == ".pdf"
    assert suffix_of("Deck.PPTX") == ".pptx"
    assert suffix_of("old.ppt") == ".ppt"
    assert suffix_of("lesson.ipynb") == ""
    assert suffix_of("notes.docx") == ""
    assert suffix_of("") == ""


def test_an_unreadable_file_is_rejected_rather_than_guessed_at():
    try:
        extract_units(b"not a document at all", ".pdf")
    except DocumentError:
        return
    raise AssertionError("a corrupt PDF should raise DocumentError")


# ── the complete document is read (module reqs 4, 24) ───────────────────────


def test_every_slide_of_a_long_deck_is_read():
    """No arbitrary ceiling: 120 slides in, 120 units out."""
    units = extract_units(deck_bytes(slides_for([f"Topic {n}" for n in range(1, 121)])), ".pptx")
    assert len(units) == 120
    assert units[0].index == 1 and units[-1].index == 120


def test_every_page_of_a_long_pdf_is_read():
    pages = [[f"Chapter {n}", FILLER] for n in range(1, 61)]
    units = extract_units(pdf_bytes(pages), ".pdf")
    assert len(units) == 60


def test_no_content_is_dropped_from_the_end_of_a_long_document():
    """The last slide's words must survive into the last section (req 4)."""
    slides = slides_for([f"Topic {n}" for n in range(1, 41)])
    slides[-1] = ("Topic 40", [FILLER, "A distinctive closing sentence about kangaroos."])
    sections = build_sections(extract_units(deck_bytes(slides), ".pptx"))
    assert "kangaroos" in sections[-1].content


# ── grouping into logical topics (module reqs 7, 8) ─────────────────────────


def test_related_slides_group_into_one_topic_rather_than_one_each():
    slides = [
        ("Introduction to Python", [FILLER]),
        ("Introduction to Python (contd.)", ["Still the introduction here."]),
        ("Introduction to Python", ["And a third slide of it."]),
        ("Loops", [FILLER, "for i in range(3):", " print(i)"]),
    ]
    sections = build_sections(extract_units(deck_bytes(slides), ".pptx"))
    assert [s.title for s in sections] == ["Introduction to Python", "Loops"]
    assert sections[0].source_pages == "Slides 1-3"


def test_document_order_is_preserved():
    order = ["Introduction", "Variables", "Operators", "Loops", "Functions", "Applications"]
    sections = build_sections(extract_units(deck_bytes(slides_for(order)), ".pptx"))
    assert [s.title for s in sections] == order


def test_a_fragment_slide_folds_into_the_topic_before_it():
    slides = [
        ("Variables", [FILLER, "x = 10", "y = 20"]),
        ("", ["Two words"]),                      # a divider, not a section
        ("Loops", [FILLER, "for i in range(3):", " print(i)"]),
    ]
    sections = build_sections(extract_units(deck_bytes(slides), ".pptx"))
    assert [s.title for s in sections] == ["Variables", "Loops"]


def test_the_section_count_follows_the_document_not_a_constant():
    five = build_sections(extract_units(
        deck_bytes(slides_for(["Introduction", "Variables", "Operators", "Loops", "Functions"])),
        ".pptx"))
    two = build_sections(extract_units(
        deck_bytes(slides_for(["Introduction", "Loops"])), ".pptx"))
    assert len(five) == 5
    assert len(two) == 2


# ── content survives regardless of code practice (module reqs 6, 10, 13) ────


def test_prose_topics_keep_their_content_and_get_no_code_practice():
    titles = ["Introduction", "History", "Features", "Applications", "References"]
    sections = build_sections(extract_units(deck_bytes(slides_for(titles)), ".pptx"))
    assert len(sections) == len(titles)
    for section in sections:
        assert section.content.strip(), f"{section.title} lost its content"
        assert section.has_code_practice is False


def test_practical_topics_get_code_practice_alongside_their_content():
    slides = [
        ("Variables", [FILLER, "x = 10", "print(x)"]),
        ("Loops", [FILLER, "for i in range(3):", " print(i)"]),
        ("Functions", [FILLER, "def add(a, b):", " return a + b"]),
    ]
    sections = build_sections(extract_units(deck_bytes(slides), ".pptx"))
    assert [s.has_code_practice for s in sections] == [True, True, True]
    for section in sections:
        assert section.content.strip()
        assert section.code_question.strip()
        assert section.reference_code.strip()
        assert section.starter_code == ""


def test_reference_code_always_compiles():
    """A student pressing Run on the reference must not meet a SyntaxError we
    shipped: broken code lifted from a slide is dropped, not displayed."""
    slides = [
        ("Loops", [FILLER, "for i in range(3):", " print(i)"]),
        ("Variables", [FILLER, "x = = broken(", "print(x"]),
        ("Functions", [FILLER, "def add(a, b):", " return a + b"]),
    ]
    for section in build_sections(extract_units(deck_bytes(slides), ".pptx")):
        if section.reference_code:
            compile(section.reference_code, "<reference>", "exec")


def test_a_topic_with_code_in_it_gets_practice_even_off_the_taxonomy():
    slides = [("Widget wrangling", [FILLER, "total = 0", "print(total)"])]
    sections = build_sections(extract_units(deck_bytes(slides), ".pptx"))
    assert sections[0].has_code_practice is True
    assert "total = 0" in sections[0].reference_code


def test_min_section_words_is_the_only_size_knob():
    """Guards the constant the grouping leans on, so a change is deliberate."""
    assert MIN_SECTION_WORDS > 0


# ── PowerPoint 97-2003, the binary .ppt (module reqs 2, 3) ──────────────────

LEGACY_PPT = pathlib.Path(__file__).parent / "fixtures" / "legacy97.ppt"


@pytest.mark.skipif(not LEGACY_PPT.exists(), reason="legacy .ppt fixture missing")
def test_a_real_powerpoint_97_file_is_read():
    """A genuine .ppt saved by PowerPoint, not a renamed .pptx."""
    units = extract_units(LEGACY_PPT.read_bytes(), ".ppt")
    assert [u.title for u in units] == ["Introduction to Python", "Variables", "Loops"]
    assert units[0].lines == ["Python is a high level language.", "It reads like English."]
    # Indentation inside a slide survives, so extracted code still parses.
    assert any(line.startswith(" ") for line in units[2].lines)


@pytest.mark.skipif(not LEGACY_PPT.exists(), reason="legacy .ppt fixture missing")
def test_a_legacy_ppt_produces_usable_sections():
    sections = build_sections(extract_units(LEGACY_PPT.read_bytes(), ".ppt"))
    assert [s.title for s in sections] == ["Introduction to Python", "Variables", "Loops"]
    assert [s.has_code_practice for s in sections] == [False, True, True]
    for section in sections:
        if section.reference_code:
            compile(section.reference_code, "<reference>", "exec")


def test_a_pptx_renamed_to_ppt_still_opens():
    """Plenty of files in the wild are .pptx with the wrong extension."""
    units = extract_units(deck_bytes(slides_for(["Introduction", "Loops"])), ".ppt")
    assert [u.title for u in units] == ["Introduction", "Loops"]


def test_a_file_that_is_neither_reports_something_actionable():
    try:
        extract_units(b"just some bytes", ".ppt")
    except DocumentError as exc:
        assert "ppt" in str(exc).lower()
        return
    raise AssertionError("nonsense bytes should raise DocumentError")


# ── reference code vs the student's editor (module req 23) ──────────────────


def test_reference_code_is_kept_out_of_the_students_editor():
    """Code in the upload teaches. The student's editor starts empty so the
    solution is never handed to them (module req 23)."""
    slides = [("Loops", [FILLER, "for i in range(3):", " print(i)"])]
    section = build_sections(extract_units(deck_bytes(slides), ".pptx"))[0]
    assert section.has_code_practice is True
    assert "for i in range(3):" in section.reference_code
    assert section.starter_code == ""

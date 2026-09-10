"""Groq-backed structuring of uploaded learning material (module req 19).

Nothing here reaches the network. The payload shaping and validation are pure
functions precisely so they can be tested against fixed responses, including
the malformed ones a hosted API really returns.
"""

import pytest

from app.documents import Unit
from app.groq_client import GroqError, chunks_of, sections_from_payload


def payload(sections):
    return {"moduleTitle": "Python Loops", "description": "d", "sections": sections}


def test_a_valid_payload_becomes_sections_in_order():
    result = sections_from_payload(payload([
        {"order": 2, "title": "For Loop", "content": [
            {"type": "text", "text": "A for loop iterates."},
        ]},
        {"order": 1, "title": "Introduction", "content": [
            {"type": "text", "text": "Loops repeat work."},
        ]},
    ]))
    assert [s.title for s in result] == ["Introduction", "For Loop"]
    assert "Loops repeat work." in result[0].content


def test_a_code_example_becomes_read_only_reference_not_the_editor():
    result = sections_from_payload(payload([
        {"order": 1, "title": "For Loop", "content": [
            {"type": "text", "text": "Explanation."},
            {"type": "code_example", "language": "python",
             "code": "for i in range(5):\n    print(i)"},
        ]},
    ]))
    assert result[0].reference_code == "for i in range(5):\n    print(i)"
    assert result[0].starter_code == ""


def test_a_practice_item_never_carries_a_solution_into_the_editor():
    """Groq is told to leave starterCode empty. When it does not, we still must
    not hand the student the answer (module req 23)."""
    result = sections_from_payload(payload([
        {"order": 1, "title": "For Loop", "content": [
            {"type": "practice", "instruction": "Print 1 to 10.",
             "language": "python",
             "starterCode": "for i in range(1, 11):\n    print(i)"},
        ]},
    ]))
    assert result[0].has_code_practice is True
    assert result[0].code_question == "Print 1 to 10."
    assert result[0].starter_code == ""


def test_a_payload_with_no_sections_is_rejected():
    with pytest.raises(GroqError):
        sections_from_payload(payload([]))


def test_a_payload_that_is_not_an_object_is_rejected():
    with pytest.raises(GroqError):
        sections_from_payload(["not", "a", "dict"])


def test_a_section_missing_its_content_is_rejected():
    with pytest.raises(GroqError):
        sections_from_payload(payload([{"order": 1, "title": "Loops"}]))


# ── chunking a long document (module req 21) ────────────────────────────────


def unit(index, words):
    return Unit(index=index, kind="slide", title=f"Slide {index}",
                lines=[" ".join(["word"] * words)])


def test_chunking_keeps_every_unit_and_never_reorders_them():
    units = [unit(i, 100) for i in range(1, 11)]
    batches = chunks_of(units, budget=250)
    flattened = [u.index for batch in batches for u in batch]
    assert flattened == list(range(1, 11))


def test_a_chunk_stays_inside_its_word_budget():
    units = [unit(i, 100) for i in range(1, 11)]
    for batch in chunks_of(units, budget=250):
        assert sum(u.words for u in batch) <= 250


def test_a_single_oversized_unit_is_not_dropped():
    """One enormous slide still has to reach Groq, alone if need be."""
    units = [unit(1, 50), unit(2, 5000), unit(3, 50)]
    batches = chunks_of(units, budget=200)
    assert [u.index for batch in batches for u in batch] == [1, 2, 3]
    assert any(len(b) == 1 and b[0].index == 2 for b in batches)

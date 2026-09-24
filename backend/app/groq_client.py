"""Structure uploaded learning material with the Groq API (module req 19).

`documents.py` already turns a PDF/PPT/PPTX into ordered Units and groups them
by the headings the file happens to have. That is fast, free and offline, but
it is not clever about *meaning*: it cannot tell a trainer's biography from a
definition, and it cannot write a practice question about what the slide
actually taught.

This module is the optional pass that can. It sends the extracted text to Groq
and asks for the same `DraftSection` list `build_sections()` returns, so the
caller can swap one for the other without knowing which ran.

Two rules shape everything here:

    The order of the document is the order of the module. Sections are sorted
    by the order the model was given, never by anything it invents.

    Reference code is never the student's editor. Whatever the model returns
    in `starterCode` is discarded (module req 23) -- an LLM told to leave it
    empty will still fill it in sometimes, and that would hand the student the
    answer.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .config import settings
from .documents import DraftSection, Unit

API_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqError(RuntimeError):
    """Groq could not be used, or returned something we will not store.

    Always recoverable: the caller falls back to the offline grouping rather
    than failing the trainer's upload.
    """


def is_configured() -> bool:
    """Is there a key to call with? No key is a normal state, not an error."""
    return bool(settings.GROQ_API_KEY)


# ── the prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You convert Python teaching material into structured learning sections.

Rules you must follow exactly:

1. PRESERVE the educational content. This is not a summary. Keep headings,
   subheadings, definitions, explanations, important concepts, examples,
   syntax, notes, bullet points, numbered lists and tables.
2. PRESERVE the order of the source material. Section 1 is the first topic in
   the document, and so on. Never reorder topics.
3. REMOVE only non-educational material: trainer names, biographies, contact
   details, institution or company details, promotional slides, thanks/Q&A
   slides, headers, footers and page numbers.
4. Do NOT shorten explanations to make the output smaller. Losing teaching
   content is worse than a long section.
5. Python code that appears in the source is REFERENCE material. Emit it as a
   "code_example" item.
6. When a topic is worth practising, add ONE "practice" item with a clear
   instruction. Its "starterCode" MUST be an empty string. Never put a
   solution, a partial solution, or the reference code in "starterCode" --
   the student writes their own code from scratch.

Reply with JSON only, in this exact shape:

{
  "sections": [
    {
      "order": 1,
      "title": "Section title",
      "content": [
        {"type": "text", "text": "Explanation in markdown."},
        {"type": "code_example", "language": "python", "code": "..."},
        {"type": "practice", "instruction": "...", "language": "python",
         "starterCode": ""}
      ]
    }
  ]
}
"""


# ── validation: what we will and will not store ─────────────────────────────


def _text_of(item: dict) -> str:
    """One content item rendered as the markdown `content` already uses."""
    kind = item.get("type")
    if kind == "text":
        return str(item.get("text") or "").strip()
    if kind == "heading":
        text = str(item.get("text") or "").strip()
        return f"### {text}" if text else ""
    if kind in ("list", "bullets"):
        items = item.get("items")
        if isinstance(items, list):
            return "\n".join(f"- {str(i).strip()}" for i in items if str(i).strip())
    if kind == "table":
        return str(item.get("text") or "").strip()
    return ""


def _section_from(raw: Any, index: int) -> DraftSection:
    if not isinstance(raw, dict):
        raise GroqError("A section was not an object.")
    content_items = raw.get("content")
    if not isinstance(content_items, list):
        raise GroqError("A section arrived without its content.")

    prose: list[str] = []
    reference = ""
    question = ""
    has_practice = False

    for item in content_items:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "code_example":
            code = str(item.get("code") or "").strip("\n")
            # The student gets a Run button on this, so it must parse. A model
            # that returns pseudo-code loses the block, not the whole section.
            if code and _compiles(code):
                reference = f"{reference}\n\n{code}".strip() if reference else code
        elif kind == "practice":
            instruction = str(item.get("instruction") or "").strip()
            if instruction:
                has_practice = True
                question = question or instruction
        else:
            text = _text_of(item)
            if text:
                prose.append(text)

    title = str(raw.get("title") or "").strip() or f"Section {index + 1}"
    return DraftSection(
        title=title[:200],
        content="\n\n".join(prose),
        has_code_practice=has_practice,
        code_question=question,
        reference_code=reference,
        # Never the model's starterCode: the student writes their own.
        starter_code="",
        source_pages=str(raw.get("sourcePages") or "").strip(),
    )


def _compiles(code: str) -> bool:
    try:
        compile(code, "<reference>", "exec")
    except (SyntaxError, ValueError):
        return False
    return True


def _order_of(raw: Any, fallback: int) -> int:
    """The order the model was asked to preserve, or its position if absent."""
    if isinstance(raw, dict):
        try:
            return int(raw.get("order", fallback))
        except (TypeError, ValueError):
            pass
    return fallback


def sections_from_payload(payload: Any) -> list[DraftSection]:
    """Validate one Groq reply and turn it into sections, in document order."""
    if not isinstance(payload, dict):
        raise GroqError("The reply was not a JSON object.")
    raw_sections = payload.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise GroqError("The reply contained no sections.")

    ordered = sorted(
        enumerate(raw_sections), key=lambda pair: (_order_of(pair[1], pair[0]), pair[0])
    )
    sections = [_section_from(raw, index) for index, raw in ordered]
    # Prose, a worked example or something to practise all count as teaching.
    # A reply with none of the three is worse than the offline grouping.
    if not any(
        s.content.strip() or s.reference_code.strip() or s.code_question.strip()
        for s in sections
    ):
        raise GroqError("The reply contained no learning content.")
    return sections


# ── chunking: a long deck does not fit in one request ───────────────────────


def chunks_of(units: list[Unit], budget: int | None = None) -> list[list[Unit]]:
    """Split units into request-sized runs, never breaking document order.

    Chunking is by *word count*, not page count: ten dense PDF pages can carry
    more text than fifty title slides, and it is the token budget that bites.
    """
    limit = budget or settings.GROQ_CHUNK_WORDS
    batches: list[list[Unit]] = []
    current: list[Unit] = []
    words = 0
    for unit in units:
        # A single oversized unit still goes somewhere: on its own.
        if current and words + unit.words > limit:
            batches.append(current)
            current, words = [], 0
        current.append(unit)
        words += unit.words
    if current:
        batches.append(current)
    return batches


def _unit_text(unit: Unit) -> str:
    head = f"[{unit.kind.capitalize()} {unit.index}] {unit.title}".rstrip()
    return "\n".join([head, *unit.lines])


# ── the call ────────────────────────────────────────────────────────────────


def _post(body: dict) -> dict:
    """One HTTP call to Groq, with the key kept to this module."""
    response = httpx.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=settings.GROQ_TIMEOUT_SEC,
    )
    if response.status_code == 429:
        raise GroqError("rate limited")
    if response.status_code >= 500:
        raise GroqError(f"server error {response.status_code}")
    if response.status_code != 200:
        # The body can echo the request; never surface it to a trainer.
        raise GroqError(f"request rejected ({response.status_code})")
    return response.json()


def _content_of(reply: dict) -> str:
    try:
        return reply["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise GroqError("The reply had no message content.")


def _call_once(text: str) -> list[DraftSection]:
    reply = _post({
        "model": settings.GROQ_MODEL,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    })
    raw = _content_of(reply)
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise GroqError("The reply was not valid JSON.")
    return sections_from_payload(payload)


def sections_for_chunk(units: list[Unit]) -> list[DraftSection]:
    """One chunk of the document, retried through the transient failures.

    Timeouts, 429s and 5xx are what a hosted API does on an ordinary day, so
    they are retried with a widening gap before the caller is told to fall back.
    """
    text = "\n\n".join(_unit_text(unit) for unit in units)
    last: Exception | None = None
    for attempt in range(settings.GROQ_RETRIES):
        try:
            return _call_once(text)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = GroqError(f"could not reach Groq ({exc.__class__.__name__})")
        except GroqError as exc:
            last = exc
        if attempt < settings.GROQ_RETRIES - 1:
            time.sleep(settings.GROQ_BACKOFF_SEC * (2 ** attempt))
    raise last or GroqError("Groq could not be reached.")

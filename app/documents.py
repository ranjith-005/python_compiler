"""Turn an uploaded PDF/PPT/PPTX into draft learning sections (module reqs 1-11).

Two steps, kept separate so either can be replaced on its own:

    extract_units()   the document -> one Unit per page or slide, in order
    build_sections()  those units  -> logical topics, in the same order

Nothing here is clever about *meaning*. It groups by the headings the document
already has, folds continuation pages into the topic they continue, and asks a
keyword taxonomy whether a topic is the practising kind. That is deliberate:
every result is a draft the trainer edits before publishing (module req 12), so
a wrong guess costs one edit, and an AI pass can be dropped in later behind the
same two functions without the callers noticing (module req 19).

The whole document is processed. There is no page or slide ceiling anywhere in
this file -- see `test_documents.py`, which builds a 120-slide deck and counts
what comes back.
"""

from __future__ import annotations

import io
import re
import struct
from dataclasses import dataclass, field

SUPPORTED_SUFFIXES = (".pdf", ".ppt", ".pptx")
UNSUPPORTED_MESSAGE = "Unsupported file format. Please upload a PDF, PPT, or PPTX file."

# A section this small is a fragment -- a title slide, a "thank you", a stray
# page number -- and is folded into the topic before it rather than standing as
# its own section (module req 7: one slide is not one section).
MIN_SECTION_WORDS = 45

# Titles that continue the previous topic instead of opening a new one.
_CONTINUATION = re.compile(
    r"(cont\.?d?\b|continued|\(\s*\d+\s*(of|/)\s*\d+\s*\)|\.\.\.$)", re.I
)


# -- the topic taxonomy (module req 11) --------------------------------------
# Order matters: the first entry whose keywords appear in a heading wins, so
# the more specific topics come first ("data type" before "type").

_TOPICS: list[tuple[str, tuple[str, ...]]] = [
    ("Introduction", ("introduction", "getting started", "what is", "overview", "about")),
    ("History", ("history", "origin", "evolution", "timeline", "background")),
    ("Features", ("feature", "characteristic", "advantage", "why python", "benefit")),
    ("Installation", ("install", "setup", "environment", "ide", "interpreter")),
    ("Course objectives", ("objective", "outcome", "syllabus", "agenda", "course plan")),
    ("Variables", ("variable", "identifier", "naming convention", "assignment")),
    ("Data types", ("data type", "datatype", "type conversion", "casting", "boolean")),
    ("Operators", ("operator", "arithmetic", "precedence", "bitwise", "modulus")),
    ("Input and output", ("input(", "print(", "print statement", "formatting", "output")),
    ("Strings", ("string", "slicing", "concatenat")),
    ("Lists", ("list", "array")),
    ("Tuples", ("tuple",)),
    ("Dictionaries", ("dictionary", "dictionaries", "key-value", "key value")),
    ("Sets", ("sets", "frozenset")),
    ("Conditional statements", ("conditional", "if statement", "if-else", "if else",
                                "decision making", "branching", "elif")),
    ("Loops", ("loop", "while", "iteration", "break", "continue", "range(")),
    ("Functions", ("function", "parameter", "argument", "return value", "lambda",
                   "recursion")),
    ("Modules and packages", ("module", "package", "import", "library", "pip")),
    ("File handling", ("file handling", "file i/o", "read file", "write file",
                       "with open")),
    ("Exception handling", ("exception", "error handling", "traceback", "raise",
                            "finally")),
    ("Classes and objects", ("class", "object", "oop", "inheritance", "polymorphism",
                             "encapsulation", "constructor")),
    ("Algorithms", ("algorithm", "sorting", "searching", "complexity")),
    ("SQL", ("sql", "database", "query", "select statement", "join")),
    ("Applications", ("application", "use case", "real world", "project", "case study")),
    ("Conclusion", ("conclusion", "summary", "recap", "thank you")),
    ("References", ("reference", "bibliography", "further reading", "credits")),
]

# Topics where running code is the point of the topic.
_CODE_TOPICS = {
    "Variables", "Data types", "Operators", "Input and output", "Strings", "Lists",
    "Tuples", "Dictionaries", "Sets", "Conditional statements", "Loops", "Functions",
    "Modules and packages", "File handling", "Exception handling", "Classes and objects",
    "Algorithms", "SQL",
}

# Topics that are read, not practised. Code practice stays off unless the
# trainer turns it on (module req 11).
_PROSE_TOPICS = {
    "Introduction", "History", "Features", "Installation", "Course objectives",
    "Applications", "Conclusion", "References",
}

_CODE_LINE = re.compile(
    r"^\s*(>>>|\.\.\.|#|print\s*\(|def\s+\w|class\s+\w|for\s+\w+\s+in\b|while\s+.+:|"
    r"if\s+.+:|elif\s+.+:|else\s*:|import\s+\w|from\s+\w+\s+import|return\b|try\s*:|"
    r"except\b|with\s+open|input\s*\(|\w+\s*=\s*[^=])"
)

_BULLET = re.compile(r"^\s*([-*•●▪‣⁃]|\d+[.)])\s+")


class DocumentError(ValueError):
    """The upload could not be read as a document we support."""


def _missing(kind: str, package: str) -> str:
    """A missing reader is a deployment mistake; say which one and how to fix it.

    Almost always this means the server was started with an interpreter that
    never had the requirements installed -- so name the package rather than
    leaving the trainer staring at "not supported".
    """
    return (
        f"{kind} support is not installed on this server (missing `{package}`). "
        f"Install the requirements for the interpreter running the app: "
        f"python -m pip install -r requirements.txt"
    )


@dataclass
class Unit:
    """One page of a PDF or one slide of a deck, in document order."""

    index: int          # 1-based
    kind: str           # 'page' | 'slide'
    title: str
    lines: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.kind.capitalize()} {self.index}"

    @property
    def words(self) -> int:
        return sum(len(line.split()) for line in self.lines)


@dataclass
class DraftSection:
    """One logical topic, ready to be written to `module_sections`."""

    title: str
    content: str
    has_code_practice: bool
    code_question: str
    starter_code: str
    source_pages: str


# -- extraction --------------------------------------------------------------


def suffix_of(filename: str) -> str:
    name = (filename or "").strip().lower()
    for suffix in SUPPORTED_SUFFIXES:
        if name.endswith(suffix):
            return suffix
    return ""


def extract_units(raw: bytes, suffix: str) -> list[Unit]:
    """The complete document, one Unit per page/slide, in order."""
    if suffix == ".pdf":
        return _extract_pdf(raw)
    if suffix in (".pptx", ".ppt"):
        return _extract_pptx(raw, suffix)
    raise DocumentError(UNSUPPORTED_MESSAGE)


def _clean(text: str, keep_indent: bool = False) -> str:
    """Collapse the whitespace a PDF or a text frame leaves behind.

    `keep_indent` keeps the leading spaces, because in a slide they are as
    likely to be a loop body as they are to be decoration -- and dropping them
    turns extracted code into an IndentationError.
    """
    collapsed = re.sub(r"[ \t\xa0]+", " ", (text or "").replace("\r", ""))
    return collapsed.rstrip() if keep_indent else collapsed.strip()


def _looks_like_heading(line: str) -> bool:
    """Short, unpunctuated, not a bullet -- the shape of a heading."""
    if not line or len(line) > 90:
        return False
    if _BULLET.match(line):
        return False
    if line.endswith((".", ",", ";", ":")) and not line.isupper():
        return False
    if _CODE_LINE.match(line):
        return False
    return len(line.split()) <= 12


def _extract_pdf(raw: bytes) -> list[Unit]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentError(_missing("PDF", "pypdf")) from exc

    try:
        reader = PdfReader(io.BytesIO(raw))
        pages = reader.pages
    except Exception as exc:
        raise DocumentError("That PDF could not be read. It may be corrupt.") from exc

    units: list[Unit] = []
    # Every page, however many there are. Read one at a time so a 200-page file
    # never has more than one page of text in memory at once.
    for number, page in enumerate(pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        lines = [_clean(line) for line in text.splitlines()]
        lines = [line for line in lines
                 if line and not re.fullmatch(r"[\d\s/of-]+", line, re.I)]
        if not lines:
            continue
        title = lines[0] if _looks_like_heading(lines[0]) else ""
        body = lines[1:] if title else lines
        units.append(Unit(index=number, kind="page", title=title, lines=body))

    if not units:
        raise DocumentError(
            "No text could be read from that PDF. If it is a scan, it needs OCR first."
        )
    return units


# -- PowerPoint 97-2003 (.ppt), the binary one ------------------------------
# A .ppt is an OLE compound file whose "PowerPoint Document" stream is a tree of
# records: an 8-byte header (version+instance, type, length) and then either a
# body or, when the low nibble of the first field is 0xF, more records. Slides
# are top-level containers of type 0x03EE, and the text inside one lands in
# either a TextBytesAtom (one byte per character) or a TextCharsAtom (UTF-16).
#
# Reading it directly keeps the server free of PowerPoint and LibreOffice; the
# alternative was telling the trainer to go and convert the file by hand.

_PPT_SLIDE = 0x03EE
_PPT_TEXT_CHARS = 0x0FA0
_PPT_TEXT_BYTES = 0x0FA8


def _ppt_records(data: bytes, start: int, end: int):
    """Walk one level of the record tree: (is_container, type, body start/end)."""
    position = start
    while position + 8 <= end:
        version_instance, record_type, length = struct.unpack_from("<HHI", data, position)
        body_start = position + 8
        body_end = body_start + length
        if body_end > end:
            break                                   # truncated: stop, keep what we have
        yield (version_instance & 0x0F) == 0x0F, record_type, body_start, body_end
        position = body_end


def _ppt_text(data: bytes, start: int, end: int, out: list[str]) -> None:
    for is_container, record_type, body_start, body_end in _ppt_records(data, start, end):
        if is_container:
            _ppt_text(data, body_start, body_end, out)
        elif record_type == _PPT_TEXT_CHARS:
            out.append(data[body_start:body_end].decode("utf-16-le", "ignore"))
        elif record_type == _PPT_TEXT_BYTES:
            out.append(data[body_start:body_end].decode("latin-1", "ignore"))


def _extract_ppt_binary(raw: bytes, cause: Exception | None = None) -> list[Unit]:
    """One Unit per slide of a PowerPoint 97-2003 file."""
    try:
        import olefile
    except ImportError as exc:
        raise DocumentError(_missing("PowerPoint 97-2003", "olefile")) from exc

    stream = io.BytesIO(raw)
    if not olefile.isOleFile(stream):
        raise DocumentError(
            "That .ppt could not be read. It is neither a PowerPoint 97-2003 file nor a "
            "renamed .pptx -- try opening it in PowerPoint and saving it again."
        ) from cause
    try:
        ole = olefile.OleFileIO(stream)
        if not ole.exists("PowerPoint Document"):
            raise DocumentError("That .ppt has no PowerPoint content in it.")
        data = ole.openstream("PowerPoint Document").read()
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError("That .ppt could not be read. It may be corrupt.") from exc

    units: list[Unit] = []
    number = 0
    for is_container, record_type, body_start, body_end in _ppt_records(data, 0, len(data)):
        if not is_container or record_type != _PPT_SLIDE:
            continue
        chunks: list[str] = []
        _ppt_text(data, body_start, body_end, chunks)
        # \r ends a paragraph and \x0b is a soft line break inside one; both are
        # simply new lines here.
        lines: list[str] = []
        for chunk in chunks:
            for line in chunk.replace("\x0b", "\r").replace("\n", "\r").split("\r"):
                cleaned = _clean(line, keep_indent=True)
                if cleaned.strip():
                    lines.append(cleaned)
        if not lines:
            continue
        number += 1
        # The first text box on a PowerPoint slide is its title placeholder.
        title = lines[0].strip() if _looks_like_heading(lines[0].strip()) else ""
        units.append(Unit(index=number, kind="slide", title=title,
                          lines=lines[1:] if title else lines))

    if not units:
        raise DocumentError("No text could be read from that .ppt file.")
    return units


def _shape_lines(shape) -> list[str]:
    """Text of one shape: paragraphs, and table cells row by row."""
    lines: list[str] = []
    if getattr(shape, "has_table", False):
        for row in shape.table.rows:
            cells = [_clean(cell.text) for cell in row.cells]
            joined = " | ".join(cell for cell in cells if cell)
            if joined:
                lines.append(joined)
        return lines
    if not getattr(shape, "has_text_frame", False):
        return lines
    for paragraph in shape.text_frame.paragraphs:
        text = _clean(
            "".join(run.text for run in paragraph.runs) or paragraph.text, keep_indent=True
        )
        if not text.strip():
            continue
        # Keep the deck's own bullet levels; they are the topic's structure.
        lines.append(("  " * min(paragraph.level, 3)) + text)
    return lines


def _extract_pptx(raw: bytes, suffix: str) -> list[Unit]:
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise DocumentError(_missing("PowerPoint", "python-pptx")) from exc

    try:
        deck = Presentation(io.BytesIO(raw))
    except Exception as exc:
        if suffix == ".ppt":
            # A .ppt is usually the 97-2003 binary format, which is a different
            # container entirely -- python-pptx only opens the zipped XML one.
            # (Plenty of ".ppt" files in the wild are really .pptx renamed,
            # which is why this is tried first.)
            return _extract_ppt_binary(raw, exc)
        raise DocumentError("That presentation could not be read. It may be corrupt.") from exc

    units: list[Unit] = []
    # Every slide in the deck, in order.
    for number, slide in enumerate(deck.slides, start=1):
        title = ""
        title_id = None
        try:
            title_shape = slide.shapes.title
            if title_shape is not None:
                title = _clean(title_shape.text)
                title_id = title_shape.shape_id
        except Exception:
            title_id = None

        lines: list[str] = []
        for shape in slide.shapes:
            # The title is the section heading; it must not also be body text.
            if title_id is not None and getattr(shape, "shape_id", None) == title_id:
                continue
            lines.extend(_shape_lines(shape))
        try:
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
                note = _clean(slide.notes_slide.notes_text_frame.text)
                if note:
                    lines.append(note)
        except Exception:
            pass

        lines = [line for line in lines if line.strip()]
        if not title and not lines:
            continue
        units.append(Unit(index=number, kind="slide", title=title, lines=lines))

    if not units:
        raise DocumentError("That presentation has no readable text.")
    return units


# -- grouping into logical topics (module reqs 6, 7, 8) ----------------------


def canonical_topic(*texts: str) -> str:
    """The taxonomy topic these words belong to, or '' if none matches."""
    haystack = " ".join(t for t in texts if t).lower()
    if not haystack.strip():
        return ""
    for name, keywords in _TOPICS:
        if any(keyword in haystack for keyword in keywords):
            return name
    return ""


def _normalise_title(title: str) -> str:
    """A title reduced to what identifies its topic.

    Deliberately does NOT strip a trailing number. "Loops 2" following "Loops"
    is already held together by the taxonomy -- both are the Loops topic -- but
    a deck of "Topic 1 ... Topic 120" is 120 different topics, and stripping the
    number would fold the whole deck into one section.
    """
    stripped = _CONTINUATION.sub("", title or "").strip(" -:.")
    return re.sub(r"\s+", " ", stripped).strip().lower()


def _is_continuation(title: str, current_title: str) -> bool:
    if not title:
        return True                                       # no heading: same topic
    if _CONTINUATION.search(title):
        return True
    return _normalise_title(title) == _normalise_title(current_title)


def _starts_new_topic(unit: Unit, current_title: str, current_topic: str,
                      current_words: int) -> bool:
    """Does this unit open a new section, or continue the one being built?"""
    if _is_continuation(unit.title, current_title):
        return False
    topic = canonical_topic(unit.title)
    if topic and current_topic and topic != current_topic:
        return True                                       # a different topic outright
    if topic and topic == current_topic:
        return False                                      # same topic, new slide
    # No taxonomy match on either side: trust the document's own heading, but
    # only once the section being built has enough in it to stand alone.
    return current_words >= MIN_SECTION_WORDS


def _format_content(lines: list[str]) -> str:
    """Body lines as light markdown: bullets stay bullets, prose stays prose."""
    out: list[str] = []
    for line in lines:
        indent = len(line) - len(line.lstrip(" "))
        text = line.strip()
        if not text:
            continue
        bullet = _BULLET.match(text)
        if bullet:
            out.append("  " * (indent // 2) + "- " + text[bullet.end():].strip())
        elif indent >= 2:
            out.append("  " * (indent // 2) + "- " + text)
        else:
            out.append(text)
    # One blank line between prose blocks so the player's markdown sees
    # paragraphs; consecutive bullets stay together as one list.
    rendered: list[str] = []
    for line in out:
        if rendered and not line.lstrip().startswith("-") and \
                not rendered[-1].lstrip().startswith("-"):
            rendered.append("")
        rendered.append(line)
    return "\n".join(rendered).strip()


def _dedent(run: list[str]) -> str:
    """Drop the run's common leading whitespace, keep the rest.

    Indentation *is* the syntax in Python, so a run lifted out of a slide has to
    keep its relative shape -- stripping every line would turn a loop body into
    an IndentationError the moment a student pressed Run.
    """
    if not run:
        return ""
    margin = min(len(line) - len(line.lstrip(" ")) for line in run if line.strip())
    return "\n".join(line[margin:].rstrip() for line in run)


def _extract_code(lines: list[str]) -> str:
    """The longest run of code-looking lines in this topic, if any."""
    best: list[str] = []
    run: list[str] = []
    for line in lines:
        text = line.strip()
        if text and _CODE_LINE.match(text) and not _BULLET.match(text):
            # Strip only the REPL prompt, never the indentation behind it.
            run.append(re.sub(r"^(\s*)(>>>|\.\.\.)\s?", r"\1", line.rstrip()))
        else:
            if len(run) > len(best):
                best = run
            run = []
    if len(run) > len(best):
        best = run
    # A single `x = 1` on its own is as likely to be prose as code.
    if len(best) < 2:
        return ""

    code = _dedent(best)
    # Text lifted out of a slide is a guess. Offering a student a Run button on
    # something that cannot parse is worse than offering them a blank example,
    # so anything that does not compile is discarded here and the caller falls
    # back to the generic starter.
    try:
        compile(code, "<starter>", "exec")
    except (SyntaxError, ValueError):
        return ""
    return code


def _practice_for(topic: str, title: str, lines: list[str]) -> tuple[bool, str, str]:
    """(has_code_practice, question, starter_code) for one topic."""
    code = _extract_code(lines)
    if topic in _PROSE_TOPICS:
        return False, "", ""
    wants = topic in _CODE_TOPICS or bool(code)
    if not wants:
        return False, "", ""

    subject = (topic or title or "this topic").strip()
    question = (
        f"Practise {subject.lower()}: run the code below, then change it and run it "
        f"again to see what happens."
    )
    starter = code or (
        f"# {subject}\n"
        f"# Write a short example here and press Run.\n"
        f"print('{subject}')\n"
    )
    return True, question, starter


def build_sections(units: list[Unit]) -> list[DraftSection]:
    """Group units into logical topics, preserving document order."""
    if not units:
        return []

    groups: list[dict] = []
    for unit in units:
        if groups:
            current = groups[-1]
            if not _starts_new_topic(unit, current["title"], current["topic"],
                                     current["words"]):
                current["lines"].extend(unit.lines)
                current["words"] += unit.words
                current["last"] = unit.index
                if not current["title"] and unit.title:
                    current["title"] = unit.title
                    current["topic"] = canonical_topic(unit.title)
                continue
        groups.append({
            "title": unit.title,
            "topic": canonical_topic(unit.title, " ".join(unit.lines[:3])),
            "lines": list(unit.lines),
            "words": unit.words + len(unit.title.split()),
            "kind": unit.kind,
            "first": unit.index,
            "last": unit.index,
        })

    # Fold fragments into the topic before them: a divider slide is part of the
    # topic it introduces, not a section a student is asked to complete.
    merged: list[dict] = []
    for group in groups:
        if merged and group["words"] < MIN_SECTION_WORDS and not group["topic"]:
            previous = merged[-1]
            if group["title"]:
                previous["lines"].append(group["title"])
            previous["lines"].extend(group["lines"])
            previous["words"] += group["words"]
            previous["last"] = group["last"]
            continue
        merged.append(group)

    sections: list[DraftSection] = []
    for order, group in enumerate(merged, start=1):
        topic = group["topic"] or canonical_topic(group["title"],
                                                  " ".join(group["lines"][:4]))
        title = (group["title"] or topic or f"Section {order}").strip()
        has_code, question, starter = _practice_for(topic, title, group["lines"])
        first, last, kind = group["first"], group["last"], group["kind"]
        plural = f"{kind.capitalize()}s" if last > first else kind.capitalize()
        pages = f"{plural} {first}-{last}" if last > first else f"{plural} {first}"
        sections.append(
            DraftSection(
                title=title[:200],
                content=_format_content(group["lines"]),
                has_code_practice=has_code,
                code_question=question,
                starter_code=starter,
                source_pages=pages,
            )
        )
    return sections

"""Request/response models shared across routers."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class Credentials(BaseModel):
    email: EmailStr
    # bcrypt only considers the first 72 bytes, so cap the length here.
    password: str = Field(min_length=8, max_length=72)
    # Which portal the account belongs to (SRS §1). Trainers and students sign
    # in through the same form but land on different dashboards.
    role: Literal["trainer", "student"] = "student"
    full_name: str = Field(default="", max_length=120)
    first_name: str = Field(default="", min_length=1, max_length=60)
    last_name: str = Field(default="", min_length=1, max_length=60)
    phone: str = Field(default="", min_length=7, max_length=30)


class PasswordChangeIn(BaseModel):
    """Changing your own password from Settings."""

    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=8, max_length=72)
    confirm_password: str = Field(min_length=8, max_length=72)


class ThemeIn(BaseModel):
    """Appearance preference (settings requirement 6)."""

    theme: Literal["system", "light", "dark"]


class ProfileIn(BaseModel):
    """Your own name and phone, edited from Settings.

    Names exist so the portals can show a person rather than an email
    address; most seeded accounts have none.
    """

    first_name: str = Field(default="", max_length=60)
    last_name: str = Field(default="", max_length=60)
    phone: str = Field(default="", max_length=30)

    @field_validator("first_name", "last_name")
    @classmethod
    def _no_markup(cls, value: str) -> str:
        """These names reach a trainer's page; keep markup out of them.

        The rendering path still needs escaping at the sink -- this only closes
        the self-service write path that Settings opened.
        """
        if "<" in value or ">" in value:
            raise ValueError("Names cannot contain < or >.")
        return value


class TestCaseIn(BaseModel):
    stdin: str = ""
    expected_output: str = ""
    is_hidden: bool = False


class ExerciseIn(BaseModel):
    """A coding exercise plus the students it goes to (SRS §5, §6, §10)."""

    title: str = Field(min_length=1, max_length=200)
    problem_statement: str = ""
    input_format: str = ""
    output_format: str = ""
    sample_input: str = ""
    sample_output: str = ""
    explanation: str = ""
    constraints: str = ""
    starter_code: str = ""
    due_date: str | None = None
    status: Literal["draft", "published"] = "published"
    test_cases: list[TestCaseIn] = Field(default_factory=list, max_length=50)
    assign_to: list[int] = Field(default_factory=list, max_length=500)


class ReviewIn(BaseModel):
    """A trainer's verdict on one submission (SRS §13)."""

    action: Literal["approve", "request_changes", "complete"]
    comment: str = Field(default="", max_length=4000)


class QueryIn(BaseModel):
    """A trainer's query or warning about an unsubmitted assignment (req 12)."""

    severity: Literal["note", "warning", "urgent"] = "note"
    message: str = Field(min_length=1, max_length=4000)


class QueryReplyIn(BaseModel):
    """The student's single response to a query."""

    reply: str = Field(min_length=1, max_length=4000)


class AssignIn(BaseModel):
    """Assign an existing exercise, e.g. from the drafts page (req 6)."""

    assign_to: list[int] = Field(default_factory=list, max_length=500)


class RunIn(BaseModel):
    """One snippet from a module's code section (req 14).

    `kind` says whose code this is. "practice" runs what the student wrote and
    remembers it. "reference" runs the section's own stored example instead --
    `code` is ignored, and nothing is saved, so pressing Run on the worked
    example cannot overwrite the work in the student's editor (module req 23).
    """

    code: str = Field(default="", max_length=100_000)
    kind: Literal["practice", "reference"] = "practice"


# -- learning modules, trainer editing (module reqs 12, 13) ------------------


class ModuleMetaIn(BaseModel):
    """A module's own name and description, edited on the review page."""

    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=500)


class SectionIn(BaseModel):
    """A new section the trainer adds by hand."""

    title: str = Field(default="", max_length=200)
    content: str = Field(default="", max_length=200_000)
    has_code_practice: bool = False
    code_question: str = Field(default="", max_length=5_000)
    # Read-only worked example vs the student's own editor (module req 23).
    reference_code: str = Field(default="", max_length=100_000)
    starter_code: str = Field(default="", max_length=100_000)


class SectionPatch(BaseModel):
    """Any subset of one section's fields. Omitted fields are left alone."""

    title: str | None = Field(default=None, max_length=200)
    content: str | None = Field(default=None, max_length=200_000)
    has_code_practice: bool | None = None
    code_question: str | None = Field(default=None, max_length=5_000)
    reference_code: str | None = Field(default=None, max_length=100_000)
    starter_code: str | None = Field(default=None, max_length=100_000)


class SectionMoveIn(BaseModel):
    direction: Literal["up", "down"]


class SectionSplitIn(BaseModel):
    """Split one section in two at a line boundary in its content."""

    at_line: int = Field(ge=1)
    title: str = Field(default="", max_length=200)


class SectionCompleteIn(BaseModel):
    """The student ticking, or un-ticking, one section (module req 9)."""

    completed: bool = True


class SolutionIn(BaseModel):
    """The student's current editor contents, autosaved as they work."""

    code: str = Field(default="", max_length=200_000)
    stdin: str = Field(default="", max_length=100_000)


# -- reopening a closed exercise --------------------------------------------


class AccessRequestIn(BaseModel):
    """A student asking their trainer to reopen an exercise past its due date."""

    message: str = Field(default="", max_length=2_000)


class AccessDecisionIn(BaseModel):
    """The trainer's answer, written for one student.

    `message` is what that student reads. Two students who asked about the same
    exercise get their own row and so can get their own answer.
    """

    action: Literal["approve", "reject"]
    message: str = Field(default="", max_length=2_000)


class NewStudentIn(BaseModel):
    """A trainer creating a student account and assigning its credentials."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    first_name: str = Field(default="", max_length=60)
    last_name: str = Field(default="", max_length=60)
    phone: str = Field(default="", max_length=30)
    # The course the welcome email congratulates them on getting into. Free
    # text: there is no courses table, and the trainer knows what they teach.
    course: str = Field(default="", max_length=120)
    send_welcome: bool = False


class ResendCredentialsIn(BaseModel):
    """Re-issuing one enrolled student's sign-in details.

    No email field: the address is whatever the account already carries. It
    arrived from wherever the student registered, and letting a trainer retype
    it here would be a way to send one student's password to another.
    """

    password: str = Field(min_length=8, max_length=72)
    course: str = Field(default="", max_length=120)


class CalendarEventIn(BaseModel):
    """One mark on the calendar: what, optionally why, and which day.

    `event_date` is validated as a plain YYYY-MM-DD rather than parsed into a
    datetime, because that is exactly what the <input type="date"> sends and
    what the grid compares against. Accepting a full timestamp here would let
    two rows for the same day sort differently.
    """

    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    event_date: str = Field(min_length=10, max_length=10)
    kind: Literal["personal", "session"] = "personal"

    @field_validator("event_date")
    @classmethod
    def _is_a_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError("Give the date as YYYY-MM-DD.") from None
        return value

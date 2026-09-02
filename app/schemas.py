"""Request/response models shared across routers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field


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
    """One practice snippet from a module's code section (req 14)."""

    code: str = Field(default="", max_length=100_000)

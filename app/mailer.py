"""Outbound email: the welcome a newly enrolled student receives.

The app has never sent mail, so this module is deliberately small and its
failure mode is deliberately soft. A trainer enrolling a student must get the
account either way -- a mail server that is missing, slow or wrong is not a
reason to lose the enrolment.

That gives two paths, and the caller does not have to care which ran:

    Configured. `deliver()` opens an SMTP connection and sends.

    Not configured. `mailto_link()` builds a link the trainer's own mail client
    opens, already filled in. The credentials still reach the student; the
    trainer just presses send.

Only `deliver()` opens a socket. Everything above it is string building, so
the message a student would receive can be asserted on without a mail server.
"""

from __future__ import annotations

import smtplib
import ssl
import textwrap
from dataclasses import dataclass
from email.message import EmailMessage
from urllib.parse import quote

from .config import settings


class MailError(RuntimeError):
    """The message could not be handed to a mail server.

    Always recoverable: the caller falls back to the mailto link rather than
    failing whatever it was doing.
    """


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    body: str


def is_configured() -> bool:
    """Is there a mail server to send through? Having none is a normal state."""
    return bool(settings.SMTP_HOST and settings.MAIL_FROM)


# ── the welcome ────────────────────────────────────────────────────────────


def welcome_message(name: str, email: str, password: str, course: str) -> Message:
    """The mail a newly enrolled student gets: greeting, course, credentials.

    Written to be read by someone who did not ask for it and does not know
    what this system is, so it says who it is from, what they are in, and
    exactly what to do next.
    """
    greeting_name = (name or "").strip() or email
    course_name = (course or "").strip()

    subject = (
        f"Welcome to {course_name} - your sign-in details"
        if course_name
        else "Your Python Learning Platform sign-in details"
    )

    enrolled_in = f'the "{course_name}" course' if course_name else "the course"
    # Wrapped after interpolation, not before: a long course name would
    # otherwise push this line well past the margin in the student's client.
    opening = textwrap.fill(
        f"Congratulations on getting into {enrolled_in}! Your place is confirmed"
        f" and your account on the Python Learning Platform is ready.",
        width=74,
    )
    body = f"""Hello {greeting_name},

{opening}

Here is how to sign in:

    Email:    {email}
    Password: {password}

Please change your password once you are in: open the profile menu in the top
right, choose Settings, and set one only you know.

We are glad to have you with us, and we are looking forward to seeing what you
build.

-- The training team
"""
    return Message(to=email, subject=subject, body=body)


def mailto_link(message: Message) -> str:
    """The same message as a link the trainer's own mail client can open.

    `quote` with an empty safe list, so the newlines and spaces that would
    otherwise break the link are percent-encoded rather than passed through.
    """
    subject = quote(message.subject, safe="")
    body = quote(message.body, safe="")
    return f"mailto:{quote(message.to, safe='@')}?subject={subject}&body={body}"


# ── delivery ───────────────────────────────────────────────────────────────


def deliver(message: Message) -> None:
    """Hand one message to the configured SMTP server.

    Raises MailError for anything that goes wrong, including a missing
    configuration, so a caller can treat "no mail server" and "mail server
    refused" the same way: fall back to the link.
    """
    if not is_configured():
        raise MailError("No mail server is configured.")

    email = EmailMessage()
    email["From"] = settings.MAIL_FROM
    email["To"] = message.to
    email["Subject"] = message.subject
    email.set_content(message.body)

    try:
        if settings.SMTP_SSL:
            server = smtplib.SMTP_SSL(
                settings.SMTP_HOST, settings.SMTP_PORT,
                timeout=settings.SMTP_TIMEOUT_SEC,
                context=ssl.create_default_context(),
            )
        else:
            server = smtplib.SMTP(
                settings.SMTP_HOST, settings.SMTP_PORT,
                timeout=settings.SMTP_TIMEOUT_SEC,
            )
        with server:
            if settings.SMTP_STARTTLS and not settings.SMTP_SSL:
                server.starttls(context=ssl.create_default_context())
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(email)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        # Never surface the server's own text to a trainer: it can echo the
        # credentials this module was asked to send.
        raise MailError(f"The mail server refused the message ({exc.__class__.__name__}).")


def send_or_link(message: Message) -> dict:
    """Try to send; report what happened either way.

    The shape the API returns: `sent` says whether it left the building, and
    `mailto` is always present so the trainer has a way through regardless.
    """
    result = {"sent": False, "mailto": mailto_link(message), "to": message.to}
    if not is_configured():
        result["detail"] = "No mail server is configured, so nothing was sent."
        return result
    try:
        deliver(message)
    except MailError as exc:
        result["detail"] = str(exc)
        return result
    result["sent"] = True
    result["detail"] = f"Sent to {message.to}."
    return result

"""How a person is shown in the UI.

A raw email address is never a display name. Most seeded accounts have an
empty `full_name`, so without this fallback the dashboards greet people with
their email address, which is what this replaces.
"""

from __future__ import annotations

from typing import Mapping


def display_name(row: Mapping) -> str:
    """The name to show for one user row, in order of preference."""
    full = (row["full_name"] or "").strip()
    if full:
        return full

    parts = f"{(row['first_name'] or '').strip()} {(row['last_name'] or '').strip()}".strip()
    if parts:
        return parts

    local = (row["email"] or "").split("@")[0]
    words = local.replace(".", " ").replace("_", " ").replace("-", " ").split()
    return " ".join(word.capitalize() for word in words) or "User"

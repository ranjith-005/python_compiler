"""Request/response models shared across routers."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class Credentials(BaseModel):
    email: EmailStr
    # bcrypt only considers the first 72 bytes, so cap the length here.
    password: str = Field(min_length=8, max_length=72)

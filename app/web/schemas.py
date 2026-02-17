from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class UserCreate(BaseModel):
    """Schema for user registration request."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str | None = Field(None, max_length=64)

    @field_validator("email")
    @classmethod
    def validate_email_lowercase(cls, v: str) -> str:
        """Ensure email is lowercase."""
        return v.lower().strip()

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Validate password has at least one letter and one number."""
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("Password must contain at least one letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one number")
        return v


class UserLogin(BaseModel):
    """Schema for user login request."""

    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def validate_email_lowercase(cls, v: str) -> str:
        """Ensure email is lowercase."""
        return v.lower().strip()


class UserResponse(BaseModel):
    """Schema for user response (safe to expose)."""

    id: int
    email: str
    display_name: str | None
    is_active: bool
    is_superuser: bool
    created_at: str


class UserInSession(BaseModel):
    """Schema for user stored in session."""

    id: int
    email: str
    display_name: str | None
    is_active: bool
    is_superuser: bool

    @property
    def display_label(self) -> str:
        """Return display name or email for UI."""
        return self.display_name or self.email.split("@")[0]

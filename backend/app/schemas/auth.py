"""Pydantic schemas for the authentication API.

Never expose `password_hash` or any raw session secret through these (or any)
schemas. `AuthUserRead` is the sanitized public-facing user shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginIn(BaseModel):
    email: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1)


class AuthUserRead(BaseModel):
    """Sanitized authenticated user — safe to return from any endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: Optional[str]
    name: str
    role: str
    store_id: UUID
    is_active: bool
    last_login_at: Optional[datetime]
    created_at: datetime

    # Store display fields resolved from the joined Store row.
    store_name: Optional[str] = None
    demo_store: bool = False


class LoginResponse(BaseModel):
    user: AuthUserRead
    # Demonstrates the same user shape is returned everywhere (no extra fields).
    expires_in_seconds: int


class ChangePasswordIn(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)
    new_password_confirm: str = Field(..., min_length=8)


class MessageOut(BaseModel):
    message: str
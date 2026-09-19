"""Pydantic schemas for User."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.auth import password_is_valid


class UserCreate(BaseModel):
    store_id: UUID
    name: str = Field(..., min_length=1, max_length=150)
    mobile: Optional[str] = Field(default=None, max_length=30)
    role: str = "ASSOCIATE"
    email: Optional[str] = Field(default=None, max_length=255)
    password: Optional[str] = Field(default=None)

    @field_validator("password")
    @classmethod
    def _password_policy(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not password_is_valid(v):
                raise ValueError(
                    f"Password must be at least 8 characters and not empty"
                )
        return v


class UserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    mobile: Optional[str] = Field(default=None, max_length=30)
    role: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=255)
    # Optional password reset by an OWNER provisioning the account.
    password: Optional[str] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)

    @field_validator("password")
    @classmethod
    def _password_policy(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v != "":
            if not password_is_valid(v):
                raise ValueError(
                    f"Password must be at least 8 characters and not empty"
                )
        return v


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    name: str
    mobile: Optional[str]
    role: str
    created_at: datetime
    updated_at: datetime
    email: Optional[str] = None
    is_active: bool = True
    last_login_at: Optional[datetime] = None

    # password_hash is deliberately never serialized.


class UserList(BaseModel):
    items: list[UserRead]
    total: int
"""Pydantic schemas for Notification."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NotificationCreate(BaseModel):
    store_id: UUID
    notif_type: str = Field(..., max_length=30)
    title: str = Field(..., min_length=1, max_length=200)
    message: Optional[str] = Field(default=None, max_length=1000)
    severity: str = "INFO"
    is_read: bool = False
    data: Optional[dict[str, Any]] = None


class NotificationUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    message: Optional[str] = Field(default=None, max_length=1000)
    severity: Optional[str] = None
    is_read: Optional[bool] = None
    data: Optional[dict[str, Any]] = None


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    notif_type: str
    title: str
    message: Optional[str]
    severity: str
    is_read: bool
    data: Optional[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationRead]
    total: int

"""Shared Pydantic schemas (common response envelopes)."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str


class ErrorItem(BaseModel):
    loc: list = []
    msg: str
    type: str


class ErrorResponse(BaseModel):
    detail: list[ErrorItem]

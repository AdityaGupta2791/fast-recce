"""Briefing data types (M8)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

BriefSource = Literal["llm", "fallback", "cached"]


class BriefResult(BaseModel):
    property_id: UUID
    brief: str
    source: BriefSource
    regenerated: bool  # True if we overwrote an existing brief


class BatchBriefResult(BaseModel):
    generated: int
    skipped_unchanged: int
    failed: int
    llm_fallbacks_used: int
    duration_seconds: float

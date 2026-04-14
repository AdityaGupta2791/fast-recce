"""Scoring data types — internal to M7."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ScoreSource = Literal["deterministic", "llm", "fallback"]


class SubScore(BaseModel):
    """One of the 8 factors that combine into relevance_score."""

    name: str                       # e.g. "type_fit"
    value: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0, le=1.0)
    source: ScoreSource
    reasoning: str = ""


class ScoringResult(BaseModel):
    """Full scoring output for one property. Mirrors properties.score_reason_json."""

    property_id: UUID
    relevance_score: float = Field(ge=0.0, le=1.0)
    sub_scores: list[SubScore]
    llm_sub_scores_used_fallback: bool


class BatchScoringResult(BaseModel):
    scored: int
    failed: int
    llm_fallbacks_used: int
    avg_score: float
    top_property_id: UUID | None
    top_property_score: float | None
    duration_seconds: float

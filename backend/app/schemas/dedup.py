"""Dedup result types — used by DedupService and consumers (M9 dashboard)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Confidence buckets:
#   >= 0.90  → auto-merge (no human needed)
#   0.50..0.90 → surface as duplicate warning for reviewer
#   <  0.50  → treated as distinct, no warning
DedupConfidence = float


class MatchSignals(BaseModel):
    """Per-signal match details. None means the signal didn't fire."""

    place_id_match: bool = False
    phone_match: bool = False
    website_match: bool = False
    distance_meters: float | None = None
    name_similarity: float | None = None
    image_hash_match: bool = False  # reserved — wired up when M6 image hashing lands


class DuplicateCandidate(BaseModel):
    """Another property that may be a duplicate of the one being checked."""

    model_config = ConfigDict(from_attributes=False)

    property_id: UUID
    canonical_name: str
    city: str
    duplicate_confidence: DedupConfidence = Field(ge=0.0, le=1.0)
    match_signals: MatchSignals


class DedupDecision(BaseModel):
    """Result of running dedup on a single new candidate or property."""

    is_duplicate: bool = False
    auto_merge: bool = False
    matched_property_id: UUID | None = None
    confidence: DedupConfidence = 0.0
    candidates: list[DuplicateCandidate] = Field(default_factory=list)


MergeStatus = Literal["merged", "skipped_self", "no_change"]


class MergeResult(BaseModel):
    source_id: UUID
    target_id: UUID
    status: MergeStatus
    contacts_moved: int = 0
    contacts_already_existed: int = 0


class BatchDedupResult(BaseModel):
    pairs_compared: int
    auto_merged: int
    flagged_for_review: int
    duration_seconds: float
    pairs: list[tuple[UUID, UUID, DedupConfidence]] = Field(default_factory=list)

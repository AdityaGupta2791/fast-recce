"""Pydantic schemas for the Discovery module.

These are mostly internal (used by the pipeline). Discovery is not exposed as
a user-facing REST resource — triggers go through /api/v1/pipeline/trigger.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.query_bank import PropertyType

CandidateStatus = Literal["pending", "processed", "failed", "skipped_duplicate"]


class DiscoveryCandidateBase(BaseModel):
    source_name: str
    external_id: str
    query_id: UUID | None = None
    name: str
    address: str | None = None
    city: str
    locality: str | None = None
    lat: float | None = None
    lng: float | None = None
    phone: str | None = None
    website: str | None = None
    google_rating: float | None = None
    google_review_count: int | None = None
    google_types: list[str] = Field(default_factory=list)
    property_type: PropertyType
    raw_result_json: dict[str, Any] = Field(default_factory=dict)


class DiscoveryCandidateCreate(DiscoveryCandidateBase):
    """Written by DiscoveryService after mapping a Google Places result."""


class DiscoveryCandidateRead(DiscoveryCandidateBase):
    """Read projection for pipeline consumers and admin debugging."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    processing_status: CandidateStatus
    error_message: str | None
    discovered_at: datetime
    processed_at: datetime | None


class DiscoveryRunRequest(BaseModel):
    """Input for triggering a discovery run."""

    cities: list[str] | None = None
    property_types: list[PropertyType] | None = None
    max_queries: int | None = Field(default=None, ge=1, le=500)


class DiscoveryRunResult(BaseModel):
    """Summary returned by DiscoveryService.discover()."""

    queries_executed: int
    google_results_total: int
    candidates_created: int
    candidates_skipped_known: int
    errors: list[str] = Field(default_factory=list)
    duration_seconds: float

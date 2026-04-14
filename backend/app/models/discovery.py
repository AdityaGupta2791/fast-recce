"""DiscoveryCandidate ORM model. Staging table for Google Places results.

A row per place_id discovered in a pipeline run. Downstream stages read
`pending` rows, process them (crawl + dedup + upsert), then mark them
`processed`, `failed`, or `skipped_duplicate`. The staging table exists so
the pipeline can restart after a crash without re-hitting the Google API.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import CANDIDATE_STATUSES, check_constraint

# JSONB on Postgres, generic JSON on SQLite (for unit tests).
_JSONType = JSONB().with_variant(JSON(), "sqlite")


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidates"
    __table_args__ = (
        CheckConstraint(
            f"processing_status {check_constraint(CANDIDATE_STATUSES)}",
            name="ck_discovery_candidates_status",
        ),
        # One candidate row per (source, external_id) — allows re-running
        # discovery idempotently without duplicate inserts.
        UniqueConstraint(
            "source_name",
            "external_id",
            name="uq_discovery_candidates_source_external",
        ),
        Index(
            "idx_discovery_candidates_status",
            "processing_status",
            "discovered_at",
        ),
        Index("idx_discovery_candidates_query", "query_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Source attribution
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    query_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("query_bank.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Normalized fields (extracted from Google Places result)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    address: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    locality: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    google_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    google_review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    google_types: Mapped[list[Any]] = mapped_column(
        _JSONType, nullable=False, default=list, server_default="[]"
    )
    property_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Raw API response for audit / re-extraction
    raw_result_json: Mapped[dict[str, Any]] = mapped_column(
        _JSONType, nullable=False, default=dict, server_default="{}"
    )

    # Pipeline state
    processing_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending"
    )
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)

    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

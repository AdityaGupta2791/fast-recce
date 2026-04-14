"""Property ORM model — the canonical entity. One row per real-world property.

This table is touched by every downstream module:
- M5 fills canonical_phone/email/website + features_json
- M6 fills duplicate_of/is_duplicate
- M7 fills relevance_score/score_reason_json/scored_at
- M8 fills short_brief/brief_generated_at
- M9 reads everything

We create it with all columns up front (M6/M7/M8 columns nullable) so each
later module is a service-only change, not a schema migration.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import PROPERTY_STATUSES, PROPERTY_TYPES, check_constraint

_JSONType = JSONB().with_variant(JSON(), "sqlite")


class Property(Base):
    __tablename__ = "properties"
    __table_args__ = (
        CheckConstraint(
            f"property_type {check_constraint(PROPERTY_TYPES)}",
            name="ck_properties_property_type",
        ),
        CheckConstraint(
            f"status {check_constraint(PROPERTY_STATUSES)}",
            name="ck_properties_status",
        ),
        CheckConstraint(
            "relevance_score IS NULL OR (relevance_score >= 0 AND relevance_score <= 1)",
            name="ck_properties_score_range",
        ),
        Index(
            "idx_properties_dashboard",
            "city", "property_type", "status", "relevance_score",
            postgresql_ops={"relevance_score": "DESC NULLS LAST"},
        ),
        Index(
            "idx_properties_unscored",
            "created_at",
            postgresql_where="scored_at IS NULL",
        ),
        Index(
            "idx_properties_unbriefed",
            "scored_at",
            postgresql_where="brief_generated_at IS NULL AND scored_at IS NOT NULL",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Identity
    canonical_name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False)

    # Address / location
    normalized_address: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    locality: Mapped[str | None] = mapped_column(String(200), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    location: Mapped[Any | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False).with_variant(
            String(255), "sqlite"
        ),
        nullable=True,
    )
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Classification
    property_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")

    # Canonical (best) contacts — set by ContactService after resolution
    canonical_website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    canonical_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    canonical_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # AI brief — set by M8
    short_brief: Mapped[str | None] = mapped_column(Text, nullable=True)
    brief_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Scoring — set by M7
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    score_reason_json: Mapped[dict[str, Any] | None] = mapped_column(_JSONType, nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Crawled features — set by M5 from CrawlResult
    features_json: Mapped[dict[str, Any]] = mapped_column(
        _JSONType, nullable=False, default=dict, server_default="{}"
    )

    # External identity
    google_place_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    google_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    google_review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Dedup chain — set by M6
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

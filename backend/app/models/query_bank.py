"""QueryBank ORM model. Managed set of discovery queries with yield tracking."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

# JSONB on Postgres, generic JSON on SQLite (for unit tests).
_JSONType = JSONB().with_variant(JSON(), "sqlite")

from app.database import Base
from app.models.enums import PROPERTY_TYPES, check_constraint


class QueryBank(Base):
    __tablename__ = "query_bank"
    __table_args__ = (
        CheckConstraint(
            f"property_type {check_constraint(PROPERTY_TYPES)}",
            name="ck_query_bank_property_type",
        ),
        UniqueConstraint("query_text", "city", name="uq_query_bank_text_city"),
        Index(
            "idx_query_bank_city_enabled",
            "city",
            postgresql_where="is_enabled = true",
        ),
        Index(
            "idx_query_bank_quality",
            "quality_score",
            postgresql_ops={"quality_score": "DESC NULLS LAST"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    query_text: Mapped[str] = mapped_column(String(500), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    locality: Mapped[str | None] = mapped_column(String(100), nullable=True)
    property_type: Mapped[str] = mapped_column(String(50), nullable=False)
    segment_tags: Mapped[list[Any]] = mapped_column(
        _JSONType, nullable=False, default=list, server_default="[]"
    )

    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_results: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_properties: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

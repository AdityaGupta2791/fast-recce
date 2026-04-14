"""Source ORM model. Registry of all external data sources."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import (
    ACCESS_POLICIES,
    CRAWL_METHODS,
    REFRESH_FREQUENCIES,
    SOURCE_TYPES,
    check_constraint,
)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(
            f"source_type {check_constraint(SOURCE_TYPES)}",
            name="ck_sources_source_type",
        ),
        CheckConstraint(
            f"access_policy {check_constraint(ACCESS_POLICIES)}",
            name="ck_sources_access_policy",
        ),
        CheckConstraint(
            f"crawl_method {check_constraint(CRAWL_METHODS)}",
            name="ck_sources_crawl_method",
        ),
        CheckConstraint(
            f"refresh_frequency {check_constraint(REFRESH_FREQUENCIES)}",
            name="ck_sources_refresh_frequency",
        ),
        Index(
            "idx_sources_enabled_type",
            "source_type",
            postgresql_where="is_enabled = true",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    access_policy: Mapped[str] = mapped_column(
        String(20), nullable=False, default="allowed"
    )
    crawl_method: Mapped[str] = mapped_column(String(20), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    refresh_frequency: Mapped[str] = mapped_column(
        String(20), nullable=False, default="daily"
    )
    parser_version: Mapped[str] = mapped_column(
        String(20), nullable=False, default="1.0"
    )
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

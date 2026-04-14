"""Pydantic schemas for the Query Bank API surface."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PropertyType = Literal[
    "boutique_hotel",
    "villa",
    "bungalow",
    "heritage_home",
    "farmhouse",
    "resort",
    "banquet_hall",
    "cafe",
    "restaurant",
    "warehouse",
    "industrial_shed",
    "office_space",
    "school_campus",
    "coworking_space",
    "rooftop_venue",
    "theatre_studio",
    "club_lounge",
    "other",
]


class QueryBankBase(BaseModel):
    query_text: str = Field(min_length=1, max_length=500)
    city: str = Field(min_length=1, max_length=100)
    locality: str | None = Field(default=None, max_length=100)
    property_type: PropertyType
    segment_tags: list[str] = Field(default_factory=list)
    is_enabled: bool = True


class QueryBankCreate(QueryBankBase):
    pass


class QueryBankUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_text: str | None = Field(default=None, min_length=1, max_length=500)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    locality: str | None = Field(default=None, max_length=100)
    property_type: PropertyType | None = None
    segment_tags: list[str] | None = None
    is_enabled: bool | None = None


class QueryBankRead(QueryBankBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    last_run_at: datetime | None
    total_runs: int
    total_results: int
    new_properties: int
    quality_score: float | None
    created_at: datetime
    updated_at: datetime


class QueryRunResult(BaseModel):
    """Input for recording a pipeline run against a query."""

    query_id: UUID
    results_count: int = Field(ge=0)
    new_properties_count: int = Field(ge=0)

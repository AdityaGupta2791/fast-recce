"""Pydantic schemas for the sources API surface."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SourceType = Literal["api", "website", "manual", "partner_feed"]
AccessPolicy = Literal["allowed", "manual_only", "restricted"]
CrawlMethod = Literal["api_call", "sitemap", "html_parser", "browser_render"]
RefreshFrequency = Literal["hourly", "daily", "weekly", "monthly"]


class SourceBase(BaseModel):
    source_name: str = Field(min_length=1, max_length=100)
    source_type: SourceType
    access_policy: AccessPolicy = "allowed"
    crawl_method: CrawlMethod
    base_url: str | None = Field(default=None, max_length=500)
    refresh_frequency: RefreshFrequency = "daily"
    parser_version: str = Field(default="1.0", max_length=20)
    rate_limit_rpm: int = Field(default=60, ge=1, le=10000)
    is_enabled: bool = True
    notes: str | None = None


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: SourceType | None = None
    access_policy: AccessPolicy | None = None
    crawl_method: CrawlMethod | None = None
    base_url: str | None = Field(default=None, max_length=500)
    refresh_frequency: RefreshFrequency | None = None
    parser_version: str | None = Field(default=None, max_length=20)
    rate_limit_rpm: int | None = Field(default=None, ge=1, le=10000)
    is_enabled: bool | None = None
    notes: str | None = None


class SourceRead(SourceBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime

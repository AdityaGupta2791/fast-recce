"""Pydantic schemas for analytics (M9)."""

from __future__ import annotations

from pydantic import BaseModel


class PipelineHealth(BaseModel):
    last_run_started_at: str | None
    last_run_status: str | None


class PropertyStats(BaseModel):
    total: int
    by_status: dict[str, int]
    by_city: dict[str, int]
    by_type: dict[str, int]


class OutreachFunnelStats(BaseModel):
    pending: int
    in_progress: int
    converted: int


class AnalyticsDashboard(BaseModel):
    properties: PropertyStats
    outreach: OutreachFunnelStats
    llm: dict[str, int]  # scored, briefed counts

"""Pydantic schemas for property review actions (M9)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

ReviewAction = Literal["approve", "reject", "do_not_contact", "merge", "reopen"]


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ReviewAction
    notes: str | None = None
    merge_into_id: UUID | None = None  # required when action == "merge"


class ReviewResponse(BaseModel):
    property_id: UUID
    status: str
    action_applied: ReviewAction
    outreach_created: bool = False
    merged_into_id: UUID | None = None
    dnc_entries_added: int = 0

"""Properties router — Lead Queue list, detail, review actions (M9)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    get_current_user,
    get_property_service,
    require_role,
)
from app.models.user import User
from app.schemas.property import PropertyDetail, PropertyListItem, PropertyRead
from app.schemas.review import ReviewRequest, ReviewResponse
from app.services.property_service import PropertyService

router = APIRouter(prefix="/api/v1/properties", tags=["properties"])


@router.get("", response_model=dict[str, Any])
async def list_properties(
    city: str | None = Query(default=None),
    property_type: str | None = Query(
        default=None,
        description="Comma-separated list of property types.",
    ),
    status: str | None = Query(
        default=None,
        description="Comma-separated list of statuses. Default: 'new'.",
    ),
    min_score: float | None = Query(default=None, ge=0, le=1),
    max_score: float | None = Query(default=None, ge=0, le=1),
    has_phone: bool | None = Query(default=None),
    has_email: bool | None = Query(default=None),
    is_duplicate: bool = Query(default=False),
    search: str | None = Query(default=None),
    sort: str = Query(default="relevance_score_desc"),
    offset: int = Query(default=0, ge=0),
    page_size: int = Query(default=50, ge=1, le=100),
    _user: User = Depends(get_current_user),
    service: PropertyService = Depends(get_property_service),
) -> dict[str, Any]:
    property_types = _split_csv(property_type)
    statuses = _split_csv(status) if status else ["new"]

    items, total = await service.list_for_dashboard(
        city=city,
        property_types=property_types,
        statuses=statuses,
        min_score=min_score,
        max_score=max_score,
        has_phone=has_phone,
        has_email=has_email,
        include_duplicates=is_duplicate,
        search=search,
        sort=sort,
        offset=offset,
        limit=page_size,
    )

    return {
        "data": [PropertyListItem.model_validate(p) for p in items],
        "meta": {
            "total_count": total,
            "offset": offset,
            "page_size": page_size,
            "has_next": offset + len(items) < total,
        },
    }


@router.get("/{property_id}", response_model=PropertyDetail)
async def get_property(
    property_id: UUID,
    _user: User = Depends(get_current_user),
    service: PropertyService = Depends(get_property_service),
) -> PropertyDetail:
    prop, contacts, outreach = await service.get_detail(property_id)

    base = PropertyRead.model_validate(prop).model_dump()
    return PropertyDetail(
        **base,
        contacts=[
            {
                "id": str(c.id),
                "contact_type": c.contact_type,
                "contact_value": c.contact_value,
                "normalized_value": c.normalized_value,
                "source_name": c.source_name,
                "source_url": c.source_url,
                "extraction_method": c.extraction_method,
                "confidence": c.confidence,
                "is_public_business_contact": c.is_public_business_contact,
                "is_primary": c.is_primary,
                "flagged_personal": c.flagged_personal,
            }
            for c in contacts
        ],
        outreach=(
            {
                "id": str(outreach.id),
                "status": outreach.status,
                "priority": outreach.priority,
                "assigned_to": str(outreach.assigned_to) if outreach.assigned_to else None,
                "outreach_channel": outreach.outreach_channel,
                "contact_attempts": outreach.contact_attempts,
                "notes": outreach.notes,
            }
            if outreach is not None
            else None
        ),
    )


@router.patch("/{property_id}/review", response_model=ReviewResponse)
async def review_property(
    property_id: UUID,
    data: ReviewRequest,
    user: User = Depends(require_role("reviewer", "admin")),
    service: PropertyService = Depends(get_property_service),
) -> ReviewResponse:
    return await service.review(property_id, data, reviewer_id=user.id)


def _split_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]

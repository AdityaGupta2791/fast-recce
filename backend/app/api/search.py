"""Public search router — user-facing, no auth (product pivot).

Kept separate from the admin routers (`properties`, `outreach`, `analytics`)
so we can evolve the public surface without touching the admin track.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_property_service, get_search_service
from app.schemas.property import PropertyDetail, PropertyRead
from app.schemas.search import SearchRequest, SearchResponse
from app.services.property_service import PropertyService
from app.services.search_service import SearchService

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    service: SearchService = Depends(get_search_service),
) -> SearchResponse:
    """Live search: infer city/type, run the pipeline, return ranked results."""
    return await service.search(request)


@router.get("/property/{property_id}", response_model=PropertyDetail)
async def get_public_property(
    property_id: UUID,
    service: PropertyService = Depends(get_property_service),
) -> PropertyDetail:
    """Read-only property detail for public consumers.

    Mirrors the admin `GET /properties/{id}` shape but is unauthenticated
    and always returns `outreach=None` (review/sales workflow data is not
    surfaced to public users).
    """
    prop, contacts, _outreach_ignored = await service.get_detail(property_id)

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
        outreach=None,
    )

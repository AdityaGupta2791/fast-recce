"""Public search router — user-facing, no auth (product pivot).

Kept separate from the admin routers (`properties`, `outreach`, `analytics`)
so we can evolve the public surface without touching the admin track.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_search_service
from app.schemas.search import SearchRequest, SearchResponse
from app.services.search_service import SearchService

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    service: SearchService = Depends(get_search_service),
) -> SearchResponse:
    """Live search: infer city/type, run the pipeline, return ranked results."""
    return await service.search(request)

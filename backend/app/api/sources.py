"""Sources API router. Mounted at /api/v1/sources. Admin-only in production."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_source_service
from app.schemas.source import (
    SourceCreate,
    SourceRead,
    SourceUpdate,
)
from app.services.source_service import SourceService

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


@router.get("", response_model=list[SourceRead])
async def list_sources(
    source_type: str | None = Query(default=None),
    is_enabled: bool | None = Query(default=None),
    service: SourceService = Depends(get_source_service),
) -> list[SourceRead]:
    sources = await service.list_sources(
        source_type=source_type, is_enabled=is_enabled
    )
    return [SourceRead.model_validate(s) for s in sources]


@router.get("/{source_id}", response_model=SourceRead)
async def get_source(
    source_id: UUID,
    service: SourceService = Depends(get_source_service),
) -> SourceRead:
    source = await service.get_source(source_id)
    return SourceRead.model_validate(source)


@router.post("", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
async def create_source(
    data: SourceCreate,
    service: SourceService = Depends(get_source_service),
) -> SourceRead:
    source = await service.create_source(data)
    return SourceRead.model_validate(source)


@router.patch("/{source_id}", response_model=SourceRead)
async def update_source(
    source_id: UUID,
    data: SourceUpdate,
    service: SourceService = Depends(get_source_service),
) -> SourceRead:
    source = await service.update_source(source_id, data)
    return SourceRead.model_validate(source)

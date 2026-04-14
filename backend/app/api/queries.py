"""Query Bank API router. Mounted at /api/v1/queries."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_query_bank_service
from app.schemas.query_bank import (
    QueryBankCreate,
    QueryBankRead,
    QueryBankUpdate,
)
from app.services.query_bank_service import QueryBankService

router = APIRouter(prefix="/api/v1/queries", tags=["queries"])


@router.get("", response_model=list[QueryBankRead])
async def list_queries(
    city: str | None = Query(default=None),
    property_type: str | None = Query(default=None),
    is_enabled: bool | None = Query(default=None),
    sort: str = Query(default="quality_score_desc"),
    service: QueryBankService = Depends(get_query_bank_service),
) -> list[QueryBankRead]:
    queries = await service.list_queries(
        city=city,
        property_type=property_type,
        is_enabled=is_enabled,
        sort_by=sort,
    )
    return [QueryBankRead.model_validate(q) for q in queries]


@router.get("/{query_id}", response_model=QueryBankRead)
async def get_query(
    query_id: UUID,
    service: QueryBankService = Depends(get_query_bank_service),
) -> QueryBankRead:
    query = await service.get_query(query_id)
    return QueryBankRead.model_validate(query)


@router.post("", response_model=QueryBankRead, status_code=status.HTTP_201_CREATED)
async def create_query(
    data: QueryBankCreate,
    service: QueryBankService = Depends(get_query_bank_service),
) -> QueryBankRead:
    query = await service.create_query(data)
    return QueryBankRead.model_validate(query)


@router.patch("/{query_id}", response_model=QueryBankRead)
async def update_query(
    query_id: UUID,
    data: QueryBankUpdate,
    service: QueryBankService = Depends(get_query_bank_service),
) -> QueryBankRead:
    query = await service.update_query(query_id, data)
    return QueryBankRead.model_validate(query)


@router.delete("/{query_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_query(
    query_id: UUID,
    service: QueryBankService = Depends(get_query_bank_service),
) -> None:
    await service.delete_query(query_id)

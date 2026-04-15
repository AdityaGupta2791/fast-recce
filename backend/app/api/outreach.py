"""Outreach router — kanban list, update, stats (M9)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_db,
    get_outreach_service,
    require_role,
)
from app.models.outreach import OutreachQueue
from app.models.property import Property
from app.models.user import User
from app.schemas.outreach import (
    OutreachRead,
    OutreachStats,
    OutreachUpdate,
)
from app.services.outreach_service import OutreachService

router = APIRouter(prefix="/api/v1/outreach", tags=["outreach"])


@router.get("", response_model=dict[str, Any])
async def list_outreach(
    status: str | None = Query(default=None, description="Comma-separated statuses."),
    assigned_to: str | None = Query(default=None, description="UUID or 'me'"),
    city: str | None = Query(default=None),
    min_priority: int | None = Query(default=None, ge=1, le=100),
    sort: str = Query(default="priority_desc"),
    offset: int = Query(default=0, ge=0),
    page_size: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    service: OutreachService = Depends(get_outreach_service),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    statuses = [s.strip() for s in status.split(",") if s.strip()] if status else None
    assigned_uuid: UUID | None = None
    if assigned_to == "me":
        assigned_uuid = user.id
    elif assigned_to:
        assigned_uuid = UUID(assigned_to)

    items, total = await service.list_items(
        statuses=statuses,
        assigned_to=assigned_uuid,
        city=city,
        min_priority=min_priority,
        sort=sort,
        offset=offset,
        limit=page_size,
    )

    # Hydrate property + assigned_to user for each outreach row.
    property_ids = {item.property_id for item in items}
    assignee_ids = {item.assigned_to for item in items if item.assigned_to is not None}

    prop_rows = (
        (await db.execute(select(Property).where(Property.id.in_(property_ids)))).scalars().all()
        if property_ids
        else []
    )
    user_rows = (
        (await db.execute(select(User).where(User.id.in_(assignee_ids)))).scalars().all()
        if assignee_ids
        else []
    )
    props_by_id = {p.id: p for p in prop_rows}
    users_by_id = {u.id: u for u in user_rows}

    serialized: list[OutreachRead] = []
    for item in items:
        prop = props_by_id.get(item.property_id)
        if prop is None:
            continue
        assignee = users_by_id.get(item.assigned_to) if item.assigned_to else None
        serialized.append(
            OutreachRead.model_validate(
                {
                    "id": item.id,
                    "status": item.status,
                    "priority": item.priority,
                    "outreach_channel": item.outreach_channel,
                    "suggested_angle": item.suggested_angle,
                    "contact_attempts": item.contact_attempts,
                    "first_contact_at": item.first_contact_at,
                    "last_contact_at": item.last_contact_at,
                    "follow_up_at": item.follow_up_at,
                    "notes": item.notes,
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                    "property": prop,
                    "assigned_to": assignee,
                }
            )
        )

    return {
        "data": serialized,
        "meta": {
            "total_count": total,
            "offset": offset,
            "page_size": page_size,
            "has_next": offset + len(items) < total,
        },
    }


@router.patch("/{outreach_id}", response_model=dict[str, Any])
async def update_outreach(
    outreach_id: UUID,
    data: OutreachUpdate,
    _user: User = Depends(require_role("reviewer", "sales", "admin")),
    service: OutreachService = Depends(get_outreach_service),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    item = await service.update(outreach_id, data)
    # Return the same shape as list items (with nested property/assignee).
    prop = await db.get(Property, item.property_id)
    assignee = await db.get(User, item.assigned_to) if item.assigned_to else None
    return OutreachRead.model_validate(
        {
            "id": item.id,
            "status": item.status,
            "priority": item.priority,
            "outreach_channel": item.outreach_channel,
            "suggested_angle": item.suggested_angle,
            "contact_attempts": item.contact_attempts,
            "first_contact_at": item.first_contact_at,
            "last_contact_at": item.last_contact_at,
            "follow_up_at": item.follow_up_at,
            "notes": item.notes,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "property": prop,
            "assigned_to": assignee,
        }
    ).model_dump()


@router.get("/stats", response_model=OutreachStats)
async def outreach_stats(
    city: str | None = Query(default=None),
    _user: User = Depends(get_current_user),
    service: OutreachService = Depends(get_outreach_service),
) -> OutreachStats:
    return await service.stats(city=city)

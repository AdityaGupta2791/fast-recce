"""Unit tests for OutreachService (M9)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ValidationError
from app.models.outreach import OutreachQueue
from app.schemas.contact import DoNotContactCreate
from app.schemas.crawl import ExtractedContact
from app.schemas.outreach import OutreachUpdate
from app.schemas.property import PropertyUpsertFromCandidate
from app.schemas.review import ReviewRequest
from app.services.contact_service import ContactService
from app.services.outreach_service import OutreachService
from app.services.property_service import PropertyService

pytestmark = pytest.mark.asyncio


async def _approve_property(
    db: AsyncSession, name: str = "Sunset Villa"
) -> OutreachQueue:
    property_service = PropertyService(db=db)
    prop = await property_service.upsert_from_candidate(
        PropertyUpsertFromCandidate(
            candidate_id=uuid.uuid4(),
            canonical_name=name,
            city="Alibaug",
            lat=18.6414,
            lng=72.8722,
            property_type="villa",
            google_place_id=f"pid_{uuid.uuid4().hex[:6]}",
            website="https://sunset.com",
        )
    )
    await property_service.review(prop.id, ReviewRequest(action="approve"))
    # fetch the created outreach row
    from sqlalchemy import select

    row = (
        await db.execute(select(OutreachQueue).where(OutreachQueue.property_id == prop.id))
    ).scalar_one()
    return row


async def test_list_outreach_filters_by_status(db_session: AsyncSession) -> None:
    a = await _approve_property(db_session, "A")
    b = await _approve_property(db_session, "B")

    service = OutreachService(db=db_session)
    # Transition b to 'contacted' via the service (which handles the side effects).
    await service.update(b.id, OutreachUpdate(status="contacted"))

    pending, total_pending = await service.list_items(statuses=["pending"])
    contacted, total_contacted = await service.list_items(statuses=["contacted"])

    assert total_pending == 1
    assert total_contacted == 1
    assert pending[0].id == a.id
    assert contacted[0].id == b.id


async def test_contacted_transition_bumps_counters(db_session: AsyncSession) -> None:
    row = await _approve_property(db_session)
    service = OutreachService(db=db_session)

    updated = await service.update(row.id, OutreachUpdate(status="contacted"))

    assert updated.status == "contacted"
    assert updated.contact_attempts == 1
    assert updated.first_contact_at is not None
    assert updated.last_contact_at is not None


async def test_invalid_transition_raises(db_session: AsyncSession) -> None:
    row = await _approve_property(db_session)
    service = OutreachService(db=db_session)

    # pending -> converted is not allowed.
    with pytest.raises(ConflictError):
        await service.update(row.id, OutreachUpdate(status="converted"))


async def test_contacted_blocked_when_property_on_dnc(db_session: AsyncSession) -> None:
    row = await _approve_property(db_session)
    property_service = PropertyService(db=db_session)
    contact_service = ContactService(db=db_session, property_service=property_service)
    await contact_service.resolve_contacts(
        row.property_id,
        [],
        [
            ExtractedContact(
                contact_type="phone",
                value="+919876543210",
                source_url="https://sunset.com",
                extraction_method="html_tel_link",
                confidence=0.85,
            )
        ],
    )
    await contact_service.add_to_do_not_contact(
        DoNotContactCreate(
            contact_type="phone",
            contact_value="+919876543210",
            reason="owner declined",
        )
    )

    service = OutreachService(db=db_session)
    with pytest.raises(ValidationError):
        await service.update(row.id, OutreachUpdate(status="contacted"))


async def test_stats_reports_totals(db_session: AsyncSession) -> None:
    a = await _approve_property(db_session, "A")
    await _approve_property(db_session, "B")

    service = OutreachService(db=db_session)
    await service.update(a.id, OutreachUpdate(status="contacted"))

    stats = await service.stats()
    assert stats.total == 2
    assert stats.by_status.get("pending") == 1
    assert stats.by_status.get("contacted") == 1
    assert 0.0 <= stats.conversion_rate <= 1.0


async def test_priority_and_notes_update(db_session: AsyncSession) -> None:
    row = await _approve_property(db_session)
    service = OutreachService(db=db_session)

    updated = await service.update(
        row.id, OutreachUpdate(priority=95, notes="high priority lead")
    )
    assert updated.priority == 95
    assert updated.notes == "high priority lead"

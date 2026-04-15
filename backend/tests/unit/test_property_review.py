"""Unit tests for the review actions on PropertyService (M9)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ValidationError
from app.models.contact import DoNotContact
from app.models.outreach import OutreachQueue
from app.schemas.crawl import ExtractedContact
from app.schemas.property import PropertyUpsertFromCandidate
from app.schemas.review import ReviewRequest
from app.services.contact_service import ContactService
from app.services.property_service import PropertyService

pytestmark = pytest.mark.asyncio


async def _make_property(db: AsyncSession, name: str = "Sunset Villa") -> uuid.UUID:
    service = PropertyService(db=db)
    prop = await service.upsert_from_candidate(
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
    return prop.id


async def test_approve_creates_outreach_entry(db_session: AsyncSession) -> None:
    prop_id = await _make_property(db_session)
    service = PropertyService(db=db_session)

    result = await service.review(prop_id, ReviewRequest(action="approve"))

    assert result.status == "approved"
    assert result.outreach_created is True

    row = (
        (
            await db_session.execute(
                select(OutreachQueue).where(OutreachQueue.property_id == prop_id)
            )
        )
        .scalar_one_or_none()
    )
    assert row is not None
    assert row.status == "pending"


async def test_double_approve_does_not_duplicate_outreach(
    db_session: AsyncSession,
) -> None:
    prop_id = await _make_property(db_session)
    service = PropertyService(db=db_session)

    await service.review(prop_id, ReviewRequest(action="approve"))
    # Reject + approve again — second approve should NOT create a second queue row.
    await service.review(prop_id, ReviewRequest(action="reject"))
    result = await service.review(prop_id, ReviewRequest(action="approve"))

    assert result.outreach_created is False

    rows = (
        (
            await db_session.execute(
                select(OutreachQueue).where(OutreachQueue.property_id == prop_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(list(rows)) == 1


async def test_reject_sets_status(db_session: AsyncSession) -> None:
    prop_id = await _make_property(db_session)
    service = PropertyService(db=db_session)

    result = await service.review(prop_id, ReviewRequest(action="reject"))
    assert result.status == "rejected"


async def test_reopen_requires_rejected_or_dnc(db_session: AsyncSession) -> None:
    prop_id = await _make_property(db_session)
    service = PropertyService(db=db_session)

    # 'new' → reopen should fail.
    with pytest.raises(ConflictError):
        await service.review(prop_id, ReviewRequest(action="reopen"))

    # reject then reopen.
    await service.review(prop_id, ReviewRequest(action="reject"))
    result = await service.review(prop_id, ReviewRequest(action="reopen"))
    assert result.status == "new"


async def test_do_not_contact_blocklists_contacts(db_session: AsyncSession) -> None:
    prop_id = await _make_property(db_session)
    contact_service = ContactService(
        db=db_session, property_service=PropertyService(db=db_session)
    )
    await contact_service.resolve_contacts(
        prop_id,
        [],
        [
            ExtractedContact(
                contact_type="phone",
                value="+919876543210",
                source_url="https://sunset.com",
                extraction_method="html_tel_link",
                confidence=0.85,
            ),
            ExtractedContact(
                contact_type="email",
                value="info@sunset.com",
                source_url="https://sunset.com",
                extraction_method="html_mailto",
                confidence=0.85,
            ),
        ],
    )

    service = PropertyService(db=db_session)
    result = await service.review(
        prop_id, ReviewRequest(action="do_not_contact", notes="owner declined")
    )

    assert result.status == "do_not_contact"
    assert result.dnc_entries_added == 2

    dnc_rows = (
        (await db_session.execute(select(DoNotContact))).scalars().all()
    )
    assert len(list(dnc_rows)) == 2


async def test_merge_sets_duplicate_flag_and_requires_target(
    db_session: AsyncSession,
) -> None:
    source_id = await _make_property(db_session, name="Source")
    target_id = await _make_property(db_session, name="Target")
    service = PropertyService(db=db_session)

    with pytest.raises(ValidationError):
        await service.review(source_id, ReviewRequest(action="merge"))

    result = await service.review(
        source_id,
        ReviewRequest(action="merge", merge_into_id=target_id),
    )
    assert result.merged_into_id == target_id

    source = await service.get(source_id)
    assert source.is_duplicate is True
    assert source.duplicate_of == target_id
    assert source.status == "reviewed"


async def test_merge_into_self_rejected(db_session: AsyncSession) -> None:
    prop_id = await _make_property(db_session)
    service = PropertyService(db=db_session)
    with pytest.raises(ValidationError):
        await service.review(
            prop_id, ReviewRequest(action="merge", merge_into_id=prop_id)
        )


async def test_list_for_dashboard_filters_duplicates_by_default(
    db_session: AsyncSession,
) -> None:
    a_id = await _make_property(db_session, name="A")
    b_id = await _make_property(db_session, name="B")
    service = PropertyService(db=db_session)
    # mark B as duplicate via the merge action.
    await service.review(
        b_id, ReviewRequest(action="merge", merge_into_id=a_id)
    )

    items, total = await service.list_for_dashboard(statuses=None)
    ids = {p.id for p in items}
    assert a_id in ids
    assert b_id not in ids
    assert total >= 1


async def test_list_for_dashboard_filters_and_count(
    db_session: AsyncSession,
) -> None:
    a_id = await _make_property(db_session, name="Alibaug Villa")
    await _make_property(db_session, name="Mumbai Resort")
    # City filter
    service = PropertyService(db=db_session)
    items, total = await service.list_for_dashboard(city="Alibaug", statuses=None)
    assert total == 2  # both are in Alibaug by the test helper default
    assert any(p.id == a_id for p in items)

"""Unit tests for DedupService (M6)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.contact import DoNotContactCreate
from app.schemas.crawl import ExtractedContact
from app.schemas.property import PropertyUpsertFromCandidate
from app.services.contact_service import ContactService
from app.services.dedup_service import (
    AUTO_MERGE_THRESHOLD,
    REVIEW_THRESHOLD,
    DedupService,
)
from app.services.property_service import PropertyService

pytestmark = pytest.mark.asyncio

# -- Fixtures helpers --------------------------------------------------


def _payload(
    name: str,
    *,
    place_id: str | None = None,
    lat: float | None = 18.6414,
    lng: float | None = 72.8722,
    city: str = "Alibaug",
    website: str | None = None,
    property_type: str = "villa",
) -> PropertyUpsertFromCandidate:
    return PropertyUpsertFromCandidate(
        candidate_id=uuid.uuid4(),
        canonical_name=name,
        city=city,
        locality="Nagaon",
        lat=lat,
        lng=lng,
        property_type=property_type,  # type: ignore[arg-type]
        google_place_id=place_id,
        website=website,
    )


def _phone_contact(value: str) -> ExtractedContact:
    return ExtractedContact(
        contact_type="phone",
        value=value,
        source_url="",
        extraction_method="api_structured",
        confidence=0.95,
    )


async def _make_property(
    db: AsyncSession,
    name: str,
    **kwargs: object,
) -> uuid.UUID:
    service = PropertyService(db=db)
    prop = await service.upsert_from_candidate(_payload(name, **kwargs))  # type: ignore[arg-type]
    return prop.id


async def _add_phone(
    db: AsyncSession, property_id: uuid.UUID, phone: str
) -> None:
    contact_service = ContactService(db=db, property_service=PropertyService(db=db))
    await contact_service.resolve_contacts(property_id, [], [_phone_contact(phone)])


def _dedup(db: AsyncSession) -> DedupService:
    return DedupService(db=db, property_service=PropertyService(db=db))


# -- Signal: place_id --------------------------------------------------


async def test_place_id_match_is_definite(db_session: AsyncSession) -> None:
    await _make_property(db_session, "Sunset Villa", place_id="ChIJabc")
    decision = await _dedup(db_session).check_candidate(
        google_place_id="ChIJabc",
        canonical_name="Anything Else",
        city="Alibaug",
        lat=None,
        lng=None,
        website=None,
    )
    assert decision.is_duplicate is True
    assert decision.confidence == 1.0
    assert decision.auto_merge is True


async def test_place_id_excludes_self(db_session: AsyncSession) -> None:
    pid = await _make_property(db_session, "Sunset Villa", place_id="ChIJabc")
    decision = await _dedup(db_session).check_candidate(
        google_place_id="ChIJabc",
        canonical_name="Sunset Villa",
        city="Alibaug",
        lat=None,
        lng=None,
        website=None,
        exclude_property_id=pid,
    )
    assert decision.is_duplicate is False


# -- Signal: phone -----------------------------------------------------


async def test_shared_phone_triggers_high_confidence(
    db_session: AsyncSession,
) -> None:
    a_id = await _make_property(db_session, "Property A", place_id="pid_A")
    await _add_phone(db_session, a_id, "+91 9876543210")

    decision = await _dedup(db_session).check_candidate(
        google_place_id="pid_B",
        canonical_name="Property B",
        city="Alibaug",
        lat=None,
        lng=None,
        website=None,
        phones=["98765 43210"],  # same phone, different formatting
    )
    assert decision.is_duplicate is True
    assert decision.matched_property_id == a_id
    assert decision.confidence >= 0.85


async def test_phone_match_ignores_unparseable_phones(
    db_session: AsyncSession,
) -> None:
    await _make_property(db_session, "Property A", place_id="pid_A")
    decision = await _dedup(db_session).check_candidate(
        google_place_id="pid_B",
        canonical_name="Property B",
        city="Alibaug",
        lat=None,
        lng=None,
        website=None,
        phones=["abc", "12-34"],
    )
    assert decision.is_duplicate is False


# -- Signal: website domain -------------------------------------------


async def test_same_website_domain_triggers_match(db_session: AsyncSession) -> None:
    await _make_property(
        db_session,
        "Property A",
        place_id="pid_A",
        website="https://www.silvanus.in/",
    )
    decision = await _dedup(db_session).check_candidate(
        google_place_id="pid_B",
        canonical_name="Different Name",
        city="Alibaug",
        lat=None,
        lng=None,
        website="http://silvanus.in/contact",
    )
    assert decision.is_duplicate is True
    assert decision.confidence >= 0.80


# -- Signal: geo + name similarity ------------------------------------


async def test_close_geo_and_similar_name_triggers_warning(
    db_session: AsyncSession,
) -> None:
    await _make_property(
        db_session,
        "Sunset Heritage Villa",
        place_id="pid_A",
        lat=18.6414,
        lng=72.8722,
    )
    decision = await _dedup(db_session).check_candidate(
        google_place_id="pid_B",
        canonical_name="Sunset Heritage Villa Resort",
        city="Alibaug",
        lat=18.6415,  # ~10 meters away
        lng=72.8722,
        website=None,
    )
    assert decision.is_duplicate is True
    assert REVIEW_THRESHOLD <= decision.confidence < AUTO_MERGE_THRESHOLD
    assert decision.candidates[0].match_signals.distance_meters is not None
    assert decision.candidates[0].match_signals.name_similarity is not None


async def test_far_geo_no_match(db_session: AsyncSession) -> None:
    await _make_property(
        db_session, "Sunset Villa", place_id="pid_A", lat=18.6414, lng=72.8722
    )
    decision = await _dedup(db_session).check_candidate(
        google_place_id="pid_B",
        canonical_name="Sunset Villa",
        city="Alibaug",
        lat=19.0760,  # Mumbai-ish, ~50km away
        lng=72.8777,
        website=None,
    )
    assert decision.is_duplicate is False


# -- merge_properties --------------------------------------------------


async def test_merge_moves_contacts_and_marks_duplicate(
    db_session: AsyncSession,
) -> None:
    target_id = await _make_property(db_session, "Sunset Villa", place_id="pid_T")
    source_id = await _make_property(db_session, "Sunset Villa Dup", place_id="pid_S")

    contact_service = ContactService(
        db=db_session, property_service=PropertyService(db=db_session)
    )
    await contact_service.resolve_contacts(
        target_id, [], [_phone_contact("+919876543210")]
    )
    await contact_service.resolve_contacts(
        source_id, [], [_phone_contact("+918888777766")]
    )

    result = await _dedup(db_session).merge_properties(
        source_id=source_id, target_id=target_id
    )

    assert result.status == "merged"
    assert result.contacts_moved == 1
    assert result.contacts_already_existed == 0

    target_contacts = await contact_service.get_contacts_for_property(target_id)
    target_normalized = {c.normalized_value for c in target_contacts}
    assert "919876543210" in target_normalized
    assert "918888777766" in target_normalized

    source_prop = await PropertyService(db_session).get(source_id)
    assert source_prop.is_duplicate is True
    assert source_prop.duplicate_of == target_id
    assert source_prop.status == "reviewed"


async def test_merge_skips_duplicate_contacts(db_session: AsyncSession) -> None:
    target_id = await _make_property(db_session, "Target", place_id="pid_T")
    source_id = await _make_property(db_session, "Source", place_id="pid_S")

    contact_service = ContactService(
        db=db_session, property_service=PropertyService(db=db_session)
    )
    # Both have the same phone — the source's row should not be moved.
    await contact_service.resolve_contacts(
        target_id, [], [_phone_contact("+919876543210")]
    )
    await contact_service.resolve_contacts(
        source_id, [], [_phone_contact("9876543210")]
    )

    result = await _dedup(db_session).merge_properties(
        source_id=source_id, target_id=target_id
    )
    assert result.contacts_moved == 0
    assert result.contacts_already_existed == 1


async def test_merge_self_is_noop(db_session: AsyncSession) -> None:
    target_id = await _make_property(db_session, "Sunset", place_id="pid_T")
    result = await _dedup(db_session).merge_properties(
        source_id=target_id, target_id=target_id
    )
    assert result.status == "skipped_self"


# -- find_duplicates_for_property -------------------------------------


async def test_find_duplicates_for_existing_property(
    db_session: AsyncSession,
) -> None:
    a_id = await _make_property(
        db_session, "Sunset Villa", place_id="pid_A", lat=18.6414, lng=72.8722
    )
    b_id = await _make_property(
        db_session, "Sunset Villa", place_id="pid_B", lat=18.6414, lng=72.8722
    )

    candidates = await _dedup(db_session).find_duplicates_for_property(a_id)
    assert any(c.property_id == b_id for c in candidates)


# -- Batch dedup -------------------------------------------------------


async def test_batch_dedup_flags_pairs_within_city(
    db_session: AsyncSession,
) -> None:
    a_id = await _make_property(
        db_session, "Sunset Villa", place_id="pid_A", lat=18.6414, lng=72.8722
    )
    b_id = await _make_property(
        db_session, "Sunset Villa", place_id="pid_B", lat=18.6414, lng=72.8722
    )
    # Distinct property in Pune — should NOT pair with the Alibaug ones.
    await _make_property(
        db_session, "Random", place_id="pid_C", city="Pune", lat=18.5204, lng=73.8567
    )

    result = await _dedup(db_session).run_batch_dedup(city="Alibaug")
    assert result.flagged_for_review >= 1
    matched_ids = {(p[0], p[1]) for p in result.pairs}
    assert (a_id, b_id) in matched_ids or (b_id, a_id) in matched_ids


async def test_batch_dedup_auto_merges_high_confidence(
    db_session: AsyncSession,
) -> None:
    """Same place_id (1.00 confidence) should auto-merge when enabled."""
    a_id = await _make_property(db_session, "First", place_id="dup_pid")
    # Force a second property with the same place_id by bypassing the place_id
    # uniqueness check that PropertyService normally enforces via upsert.
    from app.models.property import Property
    second = Property(
        canonical_name="Second",
        normalized_name="second",
        city="Alibaug",
        property_type="villa",
        status="new",
        google_place_id="dup_pid",
    )
    db_session.add(second)
    await db_session.flush()
    await db_session.refresh(second)

    result = await _dedup(db_session).run_batch_dedup(
        city="Alibaug", auto_merge=True
    )
    assert result.auto_merged >= 1

    # One of them is now is_duplicate=true and points at the other.
    a = await PropertyService(db_session).get(a_id)
    b = await PropertyService(db_session).get(second.id)
    duplicate, primary = (a, b) if a.is_duplicate else (b, a)
    assert duplicate.is_duplicate is True
    assert duplicate.duplicate_of == primary.id


# -- Confidence calc --------------------------------------------------


async def test_no_signals_returns_no_match(db_session: AsyncSession) -> None:
    await _make_property(db_session, "Sunset Villa", place_id="pid_A")
    decision = await _dedup(db_session).check_candidate(
        google_place_id=None,
        canonical_name="Totally Different Place",
        city="Pune",
        lat=None,
        lng=None,
        website=None,
    )
    assert decision.is_duplicate is False
    assert decision.candidates == []


# -- DNC interaction (sanity) -----------------------------------------


async def test_dedup_doesnt_touch_dnc_or_blocked_contacts(
    db_session: AsyncSession,
) -> None:
    """A blocked contact is silently dropped at resolve time, so dedup never
    sees it and won't use it as a match signal."""
    a_id = await _make_property(db_session, "A", place_id="pid_A")
    contact_service = ContactService(
        db=db_session, property_service=PropertyService(db=db_session)
    )
    await contact_service.add_to_do_not_contact(
        DoNotContactCreate(
            contact_type="phone", contact_value="+919876543210", reason="test"
        )
    )
    await contact_service.resolve_contacts(
        a_id, [], [_phone_contact("+919876543210")]
    )

    decision = await _dedup(db_session).check_candidate(
        google_place_id="pid_B",
        canonical_name="B",
        city="Alibaug",
        lat=None,
        lng=None,
        website=None,
        phones=["+919876543210"],
    )
    # Phone wasn't stored → no match by phone.
    assert decision.is_duplicate is False

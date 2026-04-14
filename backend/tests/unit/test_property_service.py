"""Unit tests for PropertyService."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.schemas.property import PropertyUpsertFromCandidate
from app.services.property_service import PropertyService, normalize_name

pytestmark = pytest.mark.asyncio


def _candidate_payload(
    name: str = "Sunset Heritage Villa",
    place_id: str | None = "ChIJplace123",
) -> PropertyUpsertFromCandidate:
    return PropertyUpsertFromCandidate(
        candidate_id=uuid.uuid4(),
        canonical_name=name,
        city="Alibaug",
        locality="Nagaon",
        lat=18.6414,
        lng=72.8722,
        property_type="villa",
        google_place_id=place_id,
        google_rating=4.6,
        google_review_count=120,
        website="https://sunsetvilla.com",
        features_json={"amenities": ["pool", "lawn"]},
    )


def test_normalize_name() -> None:
    assert normalize_name("The Oberoi, Mumbai") == "the oberoi mumbai"
    assert normalize_name("BOMBORA Villa- A Luxury Villa") == "bombora villa a luxury villa"
    assert normalize_name("  multiple   spaces  ") == "multiple spaces"


async def test_upsert_from_candidate_creates_new_property(
    db_session: AsyncSession,
) -> None:
    service = PropertyService(db=db_session)
    prop = await service.upsert_from_candidate(_candidate_payload())

    assert prop.canonical_name == "Sunset Heritage Villa"
    assert prop.normalized_name == "sunset heritage villa"
    assert prop.city == "Alibaug"
    assert prop.property_type == "villa"
    assert prop.status == "new"
    assert prop.canonical_website == "https://sunsetvilla.com"
    assert prop.features_json == {"amenities": ["pool", "lawn"]}


async def test_upsert_returns_existing_when_place_id_matches(
    db_session: AsyncSession,
) -> None:
    service = PropertyService(db=db_session)
    first = await service.upsert_from_candidate(_candidate_payload())
    second = await service.upsert_from_candidate(
        _candidate_payload(name="Sunset Heritage Villa Updated")
    )

    assert first.id == second.id
    assert second.canonical_name == "Sunset Heritage Villa Updated"
    assert second.normalized_name == "sunset heritage villa updated"


async def test_upsert_creates_distinct_when_no_place_id(
    db_session: AsyncSession,
) -> None:
    service = PropertyService(db=db_session)
    a = await service.upsert_from_candidate(_candidate_payload(place_id=None))
    b = await service.upsert_from_candidate(_candidate_payload(place_id=None))

    assert a.id != b.id


async def test_get_missing_raises(db_session: AsyncSession) -> None:
    service = PropertyService(db=db_session)
    with pytest.raises(NotFoundError):
        await service.get(uuid.uuid4())


async def test_update_canonical_contacts(db_session: AsyncSession) -> None:
    service = PropertyService(db=db_session)
    prop = await service.upsert_from_candidate(_candidate_payload())
    updated = await service.update_canonical_contacts(
        prop.id, phone="+919876543210", email="owner@sunset.com"
    )

    assert updated.canonical_phone == "+919876543210"
    assert updated.canonical_email == "owner@sunset.com"
    # Website preserved from candidate.
    assert updated.canonical_website == "https://sunsetvilla.com"


async def test_merge_features(db_session: AsyncSession) -> None:
    service = PropertyService(db=db_session)
    prop = await service.upsert_from_candidate(_candidate_payload())
    updated = await service.merge_features(prop.id, {"feature_tags": ["luxury"]})

    assert updated.features_json["amenities"] == ["pool", "lawn"]
    assert updated.features_json["feature_tags"] == ["luxury"]

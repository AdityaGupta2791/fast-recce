"""Unit tests for the Google-type blocklist in DiscoveryService.

Covers the "Rudra Properties" bug: searching "properties in Nagpur" used
to surface real-estate brokers. The blocklist drops these before they
hit `get_place_details` (saves Google API cost) and before they land in
our DB.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.google_places import PlaceDetails, PlaceSearchResult
from app.schemas.source import SourceCreate
from app.services.discovery_service import DiscoveryService, _is_non_shoot_type
from app.services.query_bank_service import QueryBankService
from app.services.source_service import SourceService

pytestmark = pytest.mark.asyncio


class _GoogleFake:
    def __init__(
        self,
        search_responses: dict[str, list[PlaceSearchResult]] | None = None,
        details_by_id: dict[str, PlaceDetails] | None = None,
    ) -> None:
        self.search_responses = search_responses or {}
        self.details_by_id = details_by_id or {}
        self.text_search_calls: list[str] = []
        self.details_calls: list[str] = []

    async def text_search(self, query: str, **_: Any) -> list[PlaceSearchResult]:
        self.text_search_calls.append(query)
        return self.search_responses.get(query, [])

    async def get_place_details(self, place_id: str) -> PlaceDetails:
        self.details_calls.append(place_id)
        return self.details_by_id[place_id]


def _place_search(place_id: str, name: str, types: list[str]) -> PlaceSearchResult:
    return PlaceSearchResult(
        place_id=place_id,
        name=name,
        address=f"{name}, Nagpur",
        lat=21.15,
        lng=79.09,
        types=types,
        primary_type=types[0] if types else None,
        rating=4.0,
        review_count=50,
        raw={},
    )


def _place_details(place_id: str, name: str, types: list[str]) -> PlaceDetails:
    return PlaceDetails(
        place_id=place_id,
        name=name,
        address=f"{name}, Nagpur",
        address_components=[
            {"longText": "Nagpur", "shortText": "Nagpur", "types": ["locality"]},
        ],
        lat=21.15,
        lng=79.09,
        types=types,
        primary_type=types[0] if types else None,
        phone=None,
        website=None,
        rating=4.0,
        review_count=50,
        google_maps_uri="",
        business_status="OPERATIONAL",
        raw={},
    )


async def _seed_google_source(db: AsyncSession) -> None:
    await SourceService(db=db).create_source(
        SourceCreate(
            source_name="google_places",
            source_type="api",
            access_policy="allowed",
            crawl_method="api_call",
            base_url="https://places.googleapis.com",
        )
    )


def _make_discovery(
    db: AsyncSession, google: _GoogleFake
) -> DiscoveryService:
    return DiscoveryService(
        db=db,
        google_client=google,  # type: ignore[arg-type]
        source_service=SourceService(db=db),
        query_bank_service=QueryBankService(db=db),
    )


# --- Pure function: _is_non_shoot_type -----------------------------


def test_is_non_shoot_type_catches_brokers() -> None:
    assert _is_non_shoot_type(["real_estate_agency", "establishment"]) is True
    assert _is_non_shoot_type(["doctor"]) is True
    assert _is_non_shoot_type(["bank", "finance"]) is True
    assert _is_non_shoot_type(["lodging"]) is False
    assert _is_non_shoot_type(["cafe", "restaurant"]) is False


def test_is_non_shoot_type_checks_primary_type() -> None:
    # primary_type alone should trigger even if the types array is empty.
    assert _is_non_shoot_type([], primary_type="real_estate_agency") is True
    assert _is_non_shoot_type(["establishment"], primary_type="gym") is True
    # primary_type=None is ignored.
    assert _is_non_shoot_type(["cafe"], primary_type=None) is False


# --- Integration: discover_ad_hoc skips blocklisted candidates ------


async def test_discover_ad_hoc_filters_real_estate_agency(
    db_session: AsyncSession,
) -> None:
    await _seed_google_source(db_session)
    google = _GoogleFake(
        search_responses={
            "properties in Nagpur": [
                _place_search("p_broker", "Rudra Properties Nagpur",
                              ["real_estate_agency", "establishment"]),
                _place_search("p_villa", "Heritage Villa Nagpur",
                              ["lodging"]),
            ]
        },
        details_by_id={
            "p_villa": _place_details("p_villa", "Heritage Villa Nagpur",
                                      ["lodging"]),
            # p_broker intentionally missing — proves we never call details on it.
        },
    )
    service = _make_discovery(db_session, google)

    result = await service.discover_ad_hoc(
        query_text="properties in Nagpur",
        city="Nagpur",
        property_type="other",
    )

    assert result.google_results_total == 2
    assert result.candidates_created == 1
    assert result.candidates_filtered_non_shoot == 1

    # Critical: get_place_details was NEVER called for the broker. That
    # saves money and prevents the bad row from entering our DB.
    assert google.details_calls == ["p_villa"]


async def test_discover_ad_hoc_second_pass_filter_via_place_details(
    db_session: AsyncSession,
) -> None:
    """If search types were thin but details reveal the place is a broker,
    the second-pass filter inside discover_ad_hoc must still drop it."""
    await _seed_google_source(db_session)
    google = _GoogleFake(
        search_responses={
            "properties in Nagpur": [
                _place_search("p_thin", "Ambiguous Place", ["establishment"]),
            ]
        },
        details_by_id={
            "p_thin": _place_details("p_thin", "Ambiguous Place",
                                     ["real_estate_agency"]),
        },
    )
    service = _make_discovery(db_session, google)

    result = await service.discover_ad_hoc(
        query_text="properties in Nagpur",
        city="Nagpur",
        property_type="other",
    )

    assert result.candidates_created == 0
    assert result.candidates_filtered_non_shoot == 1
    # Details WAS called once, but the candidate never persisted.
    assert google.details_calls == ["p_thin"]


async def test_discover_ad_hoc_allows_lodging_and_villas(
    db_session: AsyncSession,
) -> None:
    """Sanity check: the blocklist does NOT accidentally drop legit types."""
    await _seed_google_source(db_session)
    good_types = [
        ("lodging",), ("cafe",), ("restaurant",), ("event_venue",),
        ("art_gallery",), ("movie_theater",), ("night_club",),
    ]
    google = _GoogleFake(
        search_responses={
            "villas in Alibaug": [
                _place_search(f"p_{i}", f"Villa {i}", list(t))
                for i, t in enumerate(good_types)
            ]
        },
        details_by_id={
            f"p_{i}": _place_details(f"p_{i}", f"Villa {i}", list(t))
            for i, t in enumerate(good_types)
        },
    )
    service = _make_discovery(db_session, google)

    result = await service.discover_ad_hoc(
        query_text="villas in Alibaug",
        city="Alibaug",
        property_type="villa",
    )

    assert result.candidates_created == len(good_types)
    assert result.candidates_filtered_non_shoot == 0

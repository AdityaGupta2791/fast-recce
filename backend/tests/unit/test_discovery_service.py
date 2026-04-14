"""Unit tests for DiscoveryService (M3).

The Google Places client is swapped for a fake in-memory double so we can
drive realistic scenarios without real API calls.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenError
from app.integrations.google_places import PlaceDetails, PlaceSearchResult
from app.models.discovery import DiscoveryCandidate
from app.schemas.query_bank import QueryBankCreate
from app.schemas.source import SourceCreate, SourceUpdate
from app.services.discovery_service import DiscoveryService
from app.services.query_bank_service import QueryBankService
from app.services.source_service import SourceService

pytestmark = pytest.mark.asyncio


class FakeGooglePlacesClient:
    """In-memory stand-in for GooglePlacesClient.

    `search_responses` maps a query string → list of search results.
    `details_by_id` maps place_id → PlaceDetails.
    """

    def __init__(
        self,
        search_responses: dict[str, list[PlaceSearchResult]] | None = None,
        details_by_id: dict[str, PlaceDetails] | None = None,
    ) -> None:
        self.search_responses = search_responses or {}
        self.details_by_id = details_by_id or {}
        self.text_search_calls: list[str] = []
        self.details_calls: list[str] = []

    async def text_search(
        self, query: str, **_: Any
    ) -> list[PlaceSearchResult]:
        self.text_search_calls.append(query)
        return self.search_responses.get(query, [])

    async def get_place_details(self, place_id: str) -> PlaceDetails:
        self.details_calls.append(place_id)
        if place_id not in self.details_by_id:
            raise RuntimeError(f"no fake details for {place_id}")
        return self.details_by_id[place_id]


def _search_result(place_id: str, name: str, types: list[str] | None = None) -> PlaceSearchResult:
    return PlaceSearchResult(
        place_id=place_id,
        name=name,
        address=f"{name}, Alibaug",
        lat=18.64,
        lng=72.87,
        types=types or ["lodging"],
        primary_type="lodging",
        rating=4.5,
        review_count=100,
        raw={"id": place_id, "displayName": {"text": name}},
    )


def _place_details(place_id: str, name: str, types: list[str] | None = None) -> PlaceDetails:
    return PlaceDetails(
        place_id=place_id,
        name=name,
        address=f"{name}, Alibaug, Maharashtra",
        address_components=[
            {"longText": "Alibaug", "shortText": "Alibaug", "types": ["locality"]},
            {"longText": "Nagaon", "shortText": "Nagaon", "types": ["sublocality_level_1"]},
        ],
        lat=18.64,
        lng=72.87,
        types=types or ["lodging"],
        primary_type="lodging",
        phone="+91 9876543210",
        website="https://example.com",
        rating=4.5,
        review_count=100,
        google_maps_uri=f"https://maps.google.com/?cid={place_id}",
        business_status="OPERATIONAL",
        raw={"id": place_id, "websiteUri": "https://example.com"},
    )


async def _seed_google_source(db: AsyncSession, *, enabled: bool = True, allowed: bool = True) -> None:
    service = SourceService(db=db)
    created = await service.create_source(
        SourceCreate(
            source_name="google_places",
            source_type="api",
            access_policy="allowed" if allowed else "restricted",
            crawl_method="api_call",
            base_url="https://places.googleapis.com",
        )
    )
    if not enabled:
        await service.update_source(created.id, SourceUpdate(is_enabled=False))


async def _seed_query(
    db: AsyncSession, text: str = "villa in Alibaug", city: str = "Alibaug"
) -> Any:
    service = QueryBankService(db=db)
    return await service.create_query(
        QueryBankCreate(
            query_text=text,
            city=city,
            property_type="villa",
            segment_tags=["premium"],
        )
    )


async def test_discover_refuses_when_source_disabled(db_session: AsyncSession) -> None:
    await _seed_google_source(db_session, enabled=False)
    await _seed_query(db_session)

    service = DiscoveryService(
        db=db_session,
        google_client=FakeGooglePlacesClient(),  # type: ignore[arg-type]
        source_service=SourceService(db=db_session),
        query_bank_service=QueryBankService(db=db_session),
    )

    with pytest.raises(ForbiddenError):
        await service.discover()


async def test_discover_refuses_when_source_restricted(db_session: AsyncSession) -> None:
    await _seed_google_source(db_session, allowed=False)
    await _seed_query(db_session)

    service = DiscoveryService(
        db=db_session,
        google_client=FakeGooglePlacesClient(),  # type: ignore[arg-type]
        source_service=SourceService(db=db_session),
        query_bank_service=QueryBankService(db=db_session),
    )

    with pytest.raises(ForbiddenError):
        await service.discover()


async def test_discover_happy_path_creates_candidates(db_session: AsyncSession) -> None:
    await _seed_google_source(db_session)
    query = await _seed_query(db_session)

    fake = FakeGooglePlacesClient(
        search_responses={
            "villa in Alibaug": [
                _search_result("p_1", "Ocean Villa"),
                _search_result("p_2", "Hilltop Villa"),
            ]
        },
        details_by_id={
            "p_1": _place_details("p_1", "Ocean Villa"),
            "p_2": _place_details("p_2", "Hilltop Villa"),
        },
    )

    service = DiscoveryService(
        db=db_session,
        google_client=fake,  # type: ignore[arg-type]
        source_service=SourceService(db=db_session),
        query_bank_service=QueryBankService(db=db_session),
    )

    result = await service.discover()

    assert result.queries_executed == 1
    assert result.google_results_total == 2
    assert result.candidates_created == 2
    assert result.candidates_skipped_known == 0
    assert result.errors == []
    assert fake.details_calls == ["p_1", "p_2"]

    # Query-level yield was recorded.
    refreshed = await QueryBankService(db=db_session).get_query(query.id)
    assert refreshed.total_runs == 1
    assert refreshed.total_results == 2
    assert refreshed.new_properties == 2
    assert refreshed.quality_score == pytest.approx(1.0)


async def test_discover_skips_known_place_ids(db_session: AsyncSession) -> None:
    """Re-running discovery should not insert duplicates or call Details twice."""
    await _seed_google_source(db_session)
    await _seed_query(db_session)

    fake = FakeGooglePlacesClient(
        search_responses={
            "villa in Alibaug": [_search_result("p_1", "Ocean Villa")]
        },
        details_by_id={"p_1": _place_details("p_1", "Ocean Villa")},
    )

    svc = lambda: DiscoveryService(  # noqa: E731
        db=db_session,
        google_client=fake,  # type: ignore[arg-type]
        source_service=SourceService(db=db_session),
        query_bank_service=QueryBankService(db=db_session),
    )

    first = await svc().discover()
    second = await svc().discover()

    assert first.candidates_created == 1
    assert second.candidates_created == 0
    assert second.candidates_skipped_known == 1
    # Details should only have been fetched once — the second run short-circuits.
    assert fake.details_calls == ["p_1"]


async def test_discover_isolates_per_query_failure(db_session: AsyncSession) -> None:
    """A failing query should not kill the whole discovery run."""
    await _seed_google_source(db_session)
    good_q = await _seed_query(db_session, text="villa in Alibaug")
    await _seed_query(db_session, text="resort in Alibaug")

    class FlakyClient(FakeGooglePlacesClient):
        async def text_search(self, query: str, **_: Any) -> list[PlaceSearchResult]:
            self.text_search_calls.append(query)
            if query == "resort in Alibaug":
                raise RuntimeError("boom")
            return await super().text_search(query)

    fake = FlakyClient(
        search_responses={
            "villa in Alibaug": [_search_result("p_1", "Ocean Villa")]
        },
        details_by_id={"p_1": _place_details("p_1", "Ocean Villa")},
    )

    service = DiscoveryService(
        db=db_session,
        google_client=fake,  # type: ignore[arg-type]
        source_service=SourceService(db=db_session),
        query_bank_service=QueryBankService(db=db_session),
    )

    result = await service.discover()

    assert result.candidates_created == 1
    assert len(result.errors) == 1
    assert "resort in Alibaug" in result.errors[0]

    # Good query still recorded yield; failed query was never reached.
    qbs = QueryBankService(db=db_session)
    good_refreshed = await qbs.get_query(good_q.id)
    assert good_refreshed.total_runs == 1


async def test_discover_respects_city_filter(db_session: AsyncSession) -> None:
    await _seed_google_source(db_session)
    await _seed_query(db_session, text="villa in Alibaug", city="Alibaug")
    await _seed_query(db_session, text="villa in Pune", city="Pune")

    fake = FakeGooglePlacesClient(
        search_responses={
            "villa in Pune": [_search_result("p_pune", "Pune Villa")]
        },
        details_by_id={"p_pune": _place_details("p_pune", "Pune Villa")},
    )

    service = DiscoveryService(
        db=db_session,
        google_client=fake,  # type: ignore[arg-type]
        source_service=SourceService(db=db_session),
        query_bank_service=QueryBankService(db=db_session),
    )

    result = await service.discover(cities=["Pune"])

    assert result.queries_executed == 1
    assert fake.text_search_calls == ["villa in Pune"]
    assert result.candidates_created == 1


async def test_discover_infers_property_type_from_google_types(
    db_session: AsyncSession,
) -> None:
    """Google's `cafe` type should win over the query's default property_type."""
    await _seed_google_source(db_session)
    query_record = await _seed_query(db_session)  # property_type=villa

    fake = FakeGooglePlacesClient(
        search_responses={
            "villa in Alibaug": [_search_result("p_c", "Curious Cafe", types=["cafe"])]
        },
        details_by_id={
            "p_c": _place_details("p_c", "Curious Cafe", types=["cafe"])
        },
    )

    service = DiscoveryService(
        db=db_session,
        google_client=fake,  # type: ignore[arg-type]
        source_service=SourceService(db=db_session),
        query_bank_service=QueryBankService(db=db_session),
    )

    await service.discover()

    candidates = await service.list_recent_candidates()
    assert len(candidates) == 1
    assert candidates[0].property_type == "cafe"
    assert candidates[0].query_id == query_record.id
    assert candidates[0].locality == "Nagaon"  # extracted from address components


async def test_mark_processed_and_failed(db_session: AsyncSession) -> None:
    await _seed_google_source(db_session)
    await _seed_query(db_session)

    fake = FakeGooglePlacesClient(
        search_responses={
            "villa in Alibaug": [_search_result("p_1", "Ocean Villa")]
        },
        details_by_id={"p_1": _place_details("p_1", "Ocean Villa")},
    )

    service = DiscoveryService(
        db=db_session,
        google_client=fake,  # type: ignore[arg-type]
        source_service=SourceService(db=db_session),
        query_bank_service=QueryBankService(db=db_session),
    )

    await service.discover()
    (candidate,) = await service.list_recent_candidates()

    processed = await service.mark_processed(candidate.id)
    assert processed.processing_status == "processed"
    assert processed.error_message is None

    # Now flip a fresh candidate to failed.
    failing = DiscoveryCandidate(
        source_name="google_places",
        external_id="p_fail",
        name="Failing",
        city="Alibaug",
        property_type="villa",
        google_types=[],
        raw_result_json={},
        processing_status="pending",
    )
    db_session.add(failing)
    await db_session.flush()

    failed = await service.mark_failed(failing.id, "crawler exploded")
    assert failed.processing_status == "failed"
    assert failed.error_message == "crawler exploded"

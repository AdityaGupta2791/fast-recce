"""Unit tests for SearchService (product pivot)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.google_places import PlaceDetails, PlaceSearchResult
from app.integrations.llm import LLMScoreResult, LLMTextResult
from app.schemas.property import PropertyUpsertFromCandidate
from app.schemas.search import SearchRequest
from app.services.briefing_service import BriefingService
from app.services.contact_service import ContactService
from app.services.dedup_service import DedupService
from app.services.discovery_service import DiscoveryService
from app.services.property_service import PropertyService
from app.services.scoring_service import ScoringService
from app.services.search_service import (
    SearchService,
    _extract_location_hint,
    _infer_city,
    _infer_property_type,
)
from app.services.source_service import SourceService
from app.services.query_bank_service import QueryBankService
from app.schemas.source import SourceCreate

pytestmark = pytest.mark.asyncio


# --- Fakes ---


class FakeGoogleClient:
    def __init__(
        self,
        search_responses: dict[str, list[PlaceSearchResult]] | None = None,
        details_by_id: dict[str, PlaceDetails] | None = None,
    ) -> None:
        self.search_responses = search_responses or {}
        self.details_by_id = details_by_id or {}
        self.text_search_calls: list[str] = []

    async def text_search(self, query: str, **_: Any) -> list[PlaceSearchResult]:
        self.text_search_calls.append(query)
        return self.search_responses.get(query, [])

    async def get_place_details(self, place_id: str) -> PlaceDetails:
        return self.details_by_id[place_id]


class FakeLLMClient:
    def __init__(self, score: float = 0.7) -> None:
        self.score = score

    async def assess_shoot_fit(self, **_: Any) -> LLMScoreResult:
        return LLMScoreResult(score=self.score, reasoning="fake", source="fallback")

    async def assess_visual_uniqueness(self, **_: Any) -> LLMScoreResult:
        return LLMScoreResult(score=self.score, reasoning="fake", source="fallback")

    async def generate_brief(self, **_: Any) -> LLMTextResult:
        return LLMTextResult(text="Fake brief text.", source="fallback")


class FakeCrawlerService:
    """CrawlerService stand-in that returns no pages / no contacts."""

    async def crawl_property(self, candidate_id: str, website_url: str):  # type: ignore[no-untyped-def]
        from app.schemas.crawl import (
            CrawlResult,
            StructuredData,
            UnstructuredData,
        )

        return CrawlResult(
            candidate_id=candidate_id,
            website_url=website_url,
            pages_fetched=0,
            pages_failed=0,
            snapshot_hash="",
            crawl_status="completed",  # type: ignore[arg-type]
            duration_seconds=0.01,
            errors=[],
            structured_data=StructuredData(),
            unstructured_data=UnstructuredData(),
            media_items=[],
            pages=[],
        )


# --- Fixtures ---


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


def _place_search(place_id: str, name: str) -> PlaceSearchResult:
    return PlaceSearchResult(
        place_id=place_id,
        name=name,
        address=f"{name}, Alibaug",
        lat=18.6414,
        lng=72.8722,
        types=["lodging"],
        primary_type="lodging",
        rating=4.5,
        review_count=100,
        raw={},
    )


def _place_details(place_id: str, name: str) -> PlaceDetails:
    return PlaceDetails(
        place_id=place_id,
        name=name,
        address=f"{name}, Alibaug, Maharashtra",
        address_components=[
            {"longText": "Alibaug", "shortText": "Alibaug", "types": ["locality"]},
        ],
        lat=18.6414,
        lng=72.8722,
        types=["lodging"],
        primary_type="lodging",
        phone="+91 9876543210",
        website="https://example.com",
        rating=4.5,
        review_count=100,
        google_maps_uri="",
        business_status="OPERATIONAL",
        raw={},
    )


def _make_service(
    db: AsyncSession,
    google: FakeGoogleClient,
    llm: FakeLLMClient,
) -> SearchService:
    property_service = PropertyService(db=db)
    contact_service = ContactService(db=db, property_service=property_service)
    discovery_service = DiscoveryService(
        db=db,
        google_client=google,  # type: ignore[arg-type]
        source_service=SourceService(db=db),
        query_bank_service=QueryBankService(db=db),
    )
    return SearchService(
        db=db,
        discovery_service=discovery_service,
        crawler_service=FakeCrawlerService(),  # type: ignore[arg-type]
        contact_service=contact_service,
        dedup_service=DedupService(db=db, property_service=property_service),
        property_service=property_service,
        scoring_service=ScoringService(
            db=db,
            llm_client=llm,  # type: ignore[arg-type]
            property_service=property_service,
            contact_service=contact_service,
        ),
        briefing_service=BriefingService(
            db=db,
            llm_client=llm,  # type: ignore[arg-type]
            property_service=property_service,
            contact_service=contact_service,
        ),
    )


# --- Tests ---


def test_infer_city_finds_known_city_in_query() -> None:
    assert _infer_city("resorts in alibaug") == "Alibaug"
    assert _infer_city("Luxury villa Mumbai") == "Mumbai"
    assert _infer_city("boutique hotels navi mumbai") == "Navi Mumbai"
    assert _infer_city("no place name here") is None


def test_infer_property_type_prefers_specific_keywords() -> None:
    assert _infer_property_type("heritage villa in Alibaug") == "heritage_home"
    assert _infer_property_type("farmhouses in Pune") == "farmhouse"
    assert _infer_property_type("rooftop venue") == "rooftop_venue"
    assert _infer_property_type("nothing interesting") == "other"


def test_extract_location_hint_strips_type_and_stopwords() -> None:
    # Property-type words + stop-words are removed; what remains IS the location.
    assert _extract_location_hint("resorts in Bandra") == "bandra"
    assert _extract_location_hint("heritage villas in Alibaug") == "alibaug"
    assert _extract_location_hint("boutique hotels Mumbai") == "mumbai"
    assert _extract_location_hint("farmhouse near Karjat") == "karjat"
    # Pure type-only query yields an empty hint — that's fine, we just skip
    # the already-scraped DB lookup in that case.
    assert _extract_location_hint("cafes") == ""


async def test_search_passes_unknown_city_straight_to_google(
    db_session: AsyncSession,
) -> None:
    """A city we don't know about (Bandra) must still reach Google."""
    await _seed_google_source(db_session)
    google = FakeGoogleClient(
        search_responses={
            "resorts in Bandra": [_place_search("p_b", "Bandra Beach Resort")]
        },
        details_by_id={"p_b": _place_details("p_b", "Bandra Beach Resort")},
    )
    service = _make_service(db_session, google, FakeLLMClient())

    resp = await service.search(SearchRequest(query="resorts in Bandra"))

    # The raw query went to Google — no hardcoded-city gate.
    assert google.text_search_calls == ["resorts in Bandra"]
    # We didn't "infer" a city (Bandra isn't in the demand-scoring map), but
    # that does NOT stop the search.
    assert resp.inferred_city is None
    # The candidate was created and ingested.
    assert resp.candidates_new == 1
    # Result surfaces via the fuzzy location-hint lookup ('bandra').
    assert any("Bandra" in r.canonical_name for r in resp.results)


async def test_search_with_empty_location_hint_still_runs_google(
    db_session: AsyncSession,
) -> None:
    """A query with only a type word ('cafes') should still hit Google."""
    await _seed_google_source(db_session)
    google = FakeGoogleClient(
        search_responses={"cafes": [_place_search("p_c", "Corner Cafe")]},
        details_by_id={"p_c": _place_details("p_c", "Corner Cafe")},
    )
    service = _make_service(db_session, google, FakeLLMClient())

    resp = await service.search(SearchRequest(query="cafes"))

    assert google.text_search_calls == ["cafes"]
    assert resp.candidates_new == 1
    # No location hint means no already-scraped DB lookup — but the newly
    # scraped candidate is persisted for next time.


async def test_search_happy_path_produces_ranked_results(db_session: AsyncSession) -> None:
    await _seed_google_source(db_session)
    google = FakeGoogleClient(
        search_responses={
            "resorts in Alibaug": [
                _place_search("p_1", "Ocean Resort"),
                _place_search("p_2", "Hilltop Resort"),
            ]
        },
        details_by_id={
            "p_1": _place_details("p_1", "Ocean Resort"),
            "p_2": _place_details("p_2", "Hilltop Resort"),
        },
    )
    service = _make_service(db_session, google, FakeLLMClient())

    resp = await service.search(SearchRequest(query="resorts in Alibaug"))

    assert resp.inferred_city == "Alibaug"
    assert resp.inferred_property_type == "resort"
    assert resp.candidates_new == 2
    assert len(resp.results) == 2

    names = {r.canonical_name for r in resp.results}
    assert names == {"Ocean Resort", "Hilltop Resort"}

    # Every result is scored + briefed (via fake LLM).
    assert all(r.relevance_score is not None for r in resp.results)
    assert all(r.short_brief for r in resp.results)


async def test_search_explicit_params_win_over_inference(
    db_session: AsyncSession,
) -> None:
    await _seed_google_source(db_session)
    google = FakeGoogleClient(
        search_responses={
            "great places": [_place_search("p_1", "Pune Villa")]
        },
        details_by_id={"p_1": _place_details("p_1", "Pune Villa")},
    )
    service = _make_service(db_session, google, FakeLLMClient())

    resp = await service.search(
        SearchRequest(query="great places", city="Pune", property_type="villa")
    )

    assert resp.inferred_city == "Pune"
    assert resp.inferred_property_type == "villa"


async def test_search_isolates_per_candidate_failure(
    db_session: AsyncSession,
) -> None:
    await _seed_google_source(db_session)

    class FlakyGoogle(FakeGoogleClient):
        async def get_place_details(self, place_id: str) -> PlaceDetails:
            if place_id == "bad":
                raise RuntimeError("boom")
            return await super().get_place_details(place_id)

    google = FlakyGoogle(
        search_responses={
            "resorts in Alibaug": [
                _place_search("good", "Good Resort"),
                _place_search("bad", "Bad Resort"),
            ]
        },
        details_by_id={"good": _place_details("good", "Good Resort")},
    )
    service = _make_service(db_session, google, FakeLLMClient())

    resp = await service.search(SearchRequest(query="resorts in Alibaug"))

    # Good result still comes through; bad one is captured in errors.
    assert resp.candidates_new == 1
    assert len(resp.results) == 1
    assert any("bad" in e.lower() for e in resp.errors)


async def test_search_skips_known_candidates_already_in_db(
    db_session: AsyncSession,
) -> None:
    """Second search with the same place_id reuses the existing property."""
    await _seed_google_source(db_session)

    # Pre-insert a property with the same google_place_id.
    property_service = PropertyService(db=db_session)
    await property_service.upsert_from_candidate(
        PropertyUpsertFromCandidate(
            candidate_id=uuid4(),
            canonical_name="Ocean Resort",
            city="Alibaug",
            lat=18.6414,
            lng=72.8722,
            property_type="resort",
            google_place_id="p_1",
        )
    )

    google = FakeGoogleClient(
        search_responses={
            "resorts in Alibaug": [_place_search("p_1", "Ocean Resort")]
        },
        details_by_id={"p_1": _place_details("p_1", "Ocean Resort")},
    )
    service = _make_service(db_session, google, FakeLLMClient())

    resp = await service.search(SearchRequest(query="resorts in Alibaug"))

    # Candidate is seen by Google but skipped (no re-insert).
    assert resp.candidates_new == 0
    assert resp.candidates_skipped_known == 1
    # The existing property still surfaces in results.
    assert any(r.canonical_name == "Ocean Resort" for r in resp.results)


async def test_search_surfaces_error_when_google_source_disabled(
    db_session: AsyncSession,
) -> None:
    """With the source router, a disabled Google source no longer raises —
    it's reported as a path error so the response can still carry results
    from other sources (Airbnb on residential routes) or at least render
    an empty state + explanation for commercial routes."""
    from app.schemas.source import SourceUpdate

    source_service = SourceService(db=db_session)
    created = await source_service.create_source(
        SourceCreate(
            source_name="google_places",
            source_type="api",
            access_policy="allowed",
            crawl_method="api_call",
        )
    )
    await source_service.update_source(created.id, SourceUpdate(is_enabled=False))

    google = FakeGoogleClient()
    service = _make_service(db_session, google, FakeLLMClient())

    resp = await service.search(SearchRequest(query="resorts in Alibaug"))

    # No result rows because discovery never ran.
    assert resp.candidates_new == 0
    # A clear explanation in errors — the API layer or UI can translate this
    # to a 503 banner if it wants.
    assert any(
        "google" in e.lower() and ("disabled" in e.lower() or "forbidden" in e.lower())
        for e in resp.errors
    )

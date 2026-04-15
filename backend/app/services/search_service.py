"""SearchService — user-facing live search orchestrator (product pivot).

Flow per user search:
  1. Infer (city, property_type) from the free-text query if not provided.
  2. DiscoveryService.discover_ad_hoc → Google Places Text Search + Details.
  3. For each new candidate: crawl → contacts → dedup → upsert property → score → brief.
  4. Query the properties table filtered by (city, property_type) sorted by score.
  5. Return top N results with sub-scores + features.

Per-item failures are caught and recorded; a failed crawl on one place never
blocks the user from seeing the rest of the results.

The review/outreach workflow is NOT touched by this service. Every upserted
property defaults to status='new' and is never auto-approved.
"""

from __future__ import annotations

import re
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.discovery import DiscoveryCandidate
from app.schemas.crawl import ExtractedContact
from app.schemas.property import PropertyUpsertFromCandidate
from app.schemas.search import (
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    SearchSubScore,
)
from app.services.briefing_service import BriefingService
from app.services.contact_service import ContactService
from app.services.crawler_service import CrawlerService
from app.services.dedup_service import DedupService
from app.services.discovery_service import DiscoveryService
from app.services.property_service import PropertyService
from app.services.scoring_service import ScoringService


class SearchService:
    def __init__(
        self,
        db: AsyncSession,
        discovery_service: DiscoveryService,
        crawler_service: CrawlerService,
        contact_service: ContactService,
        dedup_service: DedupService,
        property_service: PropertyService,
        scoring_service: ScoringService,
        briefing_service: BriefingService,
    ) -> None:
        self.db = db
        self.discovery_service = discovery_service
        self.crawler_service = crawler_service
        self.contact_service = contact_service
        self.dedup_service = dedup_service
        self.property_service = property_service
        self.scoring_service = scoring_service
        self.briefing_service = briefing_service

    async def search(self, request: SearchRequest) -> SearchResponse:
        start = time.monotonic()
        errors: list[str] = []

        # Hints only — we no longer gate on city inference. Google's geocoder
        # handles "resorts in Bandra", "farmhouse Karjat", anywhere worldwide.
        # We keep the inference to:
        #   (a) pick a sensible property_type fallback for Google results
        #       that don't map cleanly to our types
        #   (b) score `location_demand` higher for known shoot-hub cities
        city_hint = request.city or _infer_city(request.query)
        property_type_hint = request.property_type or _infer_property_type(request.query)
        location_hint = _extract_location_hint(request.query) or city_hint or ""

        # 1. Discovery — always run; Google decides if the query is meaningful.
        discovery = await self.discovery_service.discover_ad_hoc(
            query_text=request.query,
            city=city_hint,
            property_type=property_type_hint,
        )
        errors.extend(discovery.errors)

        # 2. Process each new candidate through the pipeline.
        for candidate in discovery.new_candidates:
            try:
                await self._ingest_candidate(candidate)
            except Exception as exc:  # noqa: BLE001 — per-item isolation
                errors.append(f"ingest failed for '{candidate.name}': {exc}")

        # 3. Load ranked results. Fuzzy location match against city + locality
        # + canonical_name. We use `location_hint` (query minus property-type
        # and stop-words) rather than an inferred-and-validated city — Google
        # routinely tags Indian listings with narrow sub-localities ('Chaul',
        # 'Nagaon') that our query-level inference never sees. Property-type
        # filtering is skipped because Google often maps villas to the generic
        # `lodging` type.
        if location_hint:
            items = await self.property_service.find_by_location_hint(
                city_hint=location_hint,
                limit=request.max_results,
            )
        else:
            items = []

        results = [self._to_result_item(row) for row in items]

        return SearchResponse(
            query=request.query,
            inferred_city=city_hint,
            inferred_property_type=property_type_hint,
            results=results,
            candidates_discovered=discovery.google_results_total,
            candidates_new=discovery.candidates_created,
            candidates_skipped_known=discovery.candidates_skipped_known,
            duration_seconds=round(time.monotonic() - start, 3),
            errors=errors,
        )

    # --- Internals ---

    async def _ingest_candidate(self, candidate: DiscoveryCandidate) -> None:
        """Run the crawl→contacts→dedup→upsert→score→brief pipeline for one candidate."""
        # Crawl the website if there is one.
        crawl_result = None
        if candidate.website:
            crawl_result = await self.crawler_service.crawl_property(
                str(candidate.id), candidate.website
            )

        features: dict[str, Any] = {}
        if crawl_result is not None:
            features = {
                "amenities": list(crawl_result.unstructured_data.amenities),
                "feature_tags": list(crawl_result.unstructured_data.feature_tags),
                "description": crawl_result.unstructured_data.description,
            }

        # Upsert into the canonical property table.
        payload = PropertyUpsertFromCandidate(
            candidate_id=candidate.id,
            canonical_name=candidate.name,
            city=candidate.city,
            locality=candidate.locality,
            lat=candidate.lat,
            lng=candidate.lng,
            property_type=candidate.property_type,  # type: ignore[arg-type]
            google_place_id=candidate.external_id,
            google_rating=candidate.google_rating,
            google_review_count=candidate.google_review_count,
            website=candidate.website,
            features_json=features,
        )
        prop = await self.property_service.upsert_from_candidate(payload)

        # Resolve contacts (API + crawl).
        api_contacts = _api_contacts_from_candidate(candidate)
        crawl_contacts = crawl_result.all_contacts() if crawl_result else []
        await self.contact_service.resolve_contacts(
            prop.id, api_contacts, crawl_contacts
        )

        # Score + brief so the user sees ranked, explained results.
        try:
            await self.scoring_service.score_property(prop.id)
        except Exception as exc:  # noqa: BLE001
            # Scoring fallback already built-in, but if something else blows
            # up we still want to proceed (the user can see the row anyway).
            raise exc
        try:
            await self.briefing_service.generate_brief(prop.id)
        except Exception:  # noqa: BLE001 — brief failure should not block
            pass

        # Mark the candidate as processed so an admin running the pipeline
        # later doesn't double-process it.
        candidate.processing_status = "processed"
        await self.db.flush()

    def _to_result_item(self, row: Any) -> SearchResultItem:
        sub_scores: list[SearchSubScore] = []
        reason = getattr(row, "score_reason_json", None)
        if isinstance(reason, dict):
            for s in reason.get("sub_scores") or []:
                if not isinstance(s, dict):
                    continue
                try:
                    sub_scores.append(
                        SearchSubScore(
                            name=str(s["name"]),
                            value=float(s["value"]),
                            weight=float(s["weight"]),
                            source=s.get("source") or "deterministic",  # type: ignore[arg-type]
                        )
                    )
                except (KeyError, ValueError, TypeError):
                    continue

        return SearchResultItem(
            id=row.id,
            canonical_name=row.canonical_name,
            city=row.city,
            locality=row.locality,
            property_type=row.property_type,
            relevance_score=row.relevance_score,
            short_brief=row.short_brief,
            canonical_phone=row.canonical_phone,
            canonical_email=row.canonical_email,
            canonical_website=row.canonical_website,
            google_rating=row.google_rating,
            google_review_count=row.google_review_count,
            sub_scores=sub_scores,
            features=row.features_json or {},
        )


# --- Module-level helpers ---


# Cities that commonly appear in shoot-relevant searches (PRD + neighbors we've
# actually seen in real data). Matched case-insensitively with word boundaries.
_KNOWN_CITIES: tuple[str, ...] = (
    "Mumbai",
    "Thane",
    "Navi Mumbai",
    "Lonavala",
    "Khandala",
    "Pune",
    "Alibaug",
    "Alibag",
    "Nagaon",
    "Akshi",
    "Chaul",
    "Varasoli",
    "Kihim",
    "Goa",
    "Delhi",
    "Bangalore",
    "Bengaluru",
    "Hyderabad",
)


# Property type keyword map. First match wins.
_PROPERTY_TYPE_KEYWORDS: list[tuple[str, str]] = [
    ("heritage home", "heritage_home"),
    ("heritage", "heritage_home"),
    ("boutique hotel", "boutique_hotel"),
    ("banquet hall", "banquet_hall"),
    ("banquet", "banquet_hall"),
    ("farmhouse", "farmhouse"),
    ("farm house", "farmhouse"),
    ("farm stay", "farmhouse"),
    ("villa", "villa"),
    ("bungalow", "bungalow"),
    ("resort", "resort"),
    ("warehouse", "warehouse"),
    ("industrial shed", "industrial_shed"),
    ("rooftop", "rooftop_venue"),
    ("terrace", "rooftop_venue"),
    ("theatre", "theatre_studio"),
    ("theater", "theatre_studio"),
    ("studio", "theatre_studio"),
    ("school", "school_campus"),
    ("college", "school_campus"),
    ("coworking", "coworking_space"),
    ("co-working", "coworking_space"),
    ("office", "office_space"),
    ("club", "club_lounge"),
    ("lounge", "club_lounge"),
    ("cafe", "cafe"),
    ("café", "cafe"),
    ("restaurant", "restaurant"),
    ("hotel", "boutique_hotel"),
]


def _infer_city(query: str) -> str | None:
    """Return the first known city name found in the query (case-insensitive).

    Longer / multi-word names are matched first so 'Navi Mumbai' wins over
    'Mumbai' when both occur in the query. Result is only used as a scoring
    hint (`location_demand`) — it does NOT gate the search.
    """
    normalized = " " + query.lower() + " "
    for city in sorted(_KNOWN_CITIES, key=len, reverse=True):
        if re.search(rf"(?<![a-z]){re.escape(city.lower())}(?![a-z])", normalized):
            return city
    return None


# Words to strip when deriving a location hint from the query text.
_LOCATION_HINT_STOP_WORDS: frozenset[str] = frozenset({
    "in", "near", "at", "around", "close", "to", "the", "a", "an",
    "some", "any", "best", "top", "nice", "good", "for", "rent",
    "rental", "booking", "stays", "stay",
})


def _extract_location_hint(query: str) -> str:
    """Return the substring most likely to be a location.

    Strips known property-type keywords (villa, resort, cafe, ...) and stop-
    words (in, near, at, ...). Whatever remains is handed to
    `PropertyService.find_by_location_hint` to surface already-scraped
    properties. Works for any city in the world because we don't consult a
    hardcoded list — we simply remove the parts of the query we know
    AREN'T location.

    Examples:
        'resorts in Bandra'       → 'bandra'
        'heritage villas alibaug' → 'alibaug'
        'farmhouse near Karjat'   → 'karjat'
        'cafes'                   → ''
    """
    tokens = re.findall(r"[a-z0-9]+", query.lower())
    property_type_words: set[str] = set()
    for phrase, _mapped in _PROPERTY_TYPE_KEYWORDS:
        property_type_words.update(phrase.split())

    def _is_type_or_plural(token: str) -> bool:
        # Strip trailing 's' so 'resorts' matches 'resort', 'villas' matches 'villa'.
        stem = token.rstrip("s")
        return token in property_type_words or stem in property_type_words

    kept = [
        t for t in tokens
        if t not in _LOCATION_HINT_STOP_WORDS and not _is_type_or_plural(t)
    ]
    return " ".join(kept)


def _infer_property_type(query: str) -> str:
    """Return the first matching property type; fall back to 'other'."""
    q = query.lower()
    for keyword, mapped in _PROPERTY_TYPE_KEYWORDS:
        if keyword in q:
            return mapped
    return "other"


def _api_contacts_from_candidate(c: DiscoveryCandidate) -> list[ExtractedContact]:
    contacts: list[ExtractedContact] = []
    if c.phone:
        contacts.append(
            ExtractedContact(
                contact_type="phone",
                value=c.phone,
                source_url="",
                extraction_method="api_structured",
                confidence=0.95,
            )
        )
    if c.website:
        contacts.append(
            ExtractedContact(
                contact_type="website",
                value=c.website,
                source_url="",
                extraction_method="api_structured",
                confidence=0.95,
            )
        )
    return contacts

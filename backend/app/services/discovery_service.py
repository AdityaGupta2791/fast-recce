"""DiscoveryService — M3. Turns query bank entries into candidate rows.

Pipeline flow per run:
1. Pull enabled queries from QueryBankService (filtered by city/type if given).
2. Confirm `google_places` source is allowed via SourceService (policy gate).
3. For each query, call Google Places Text Search.
4. For each new place_id, call Place Details for richer fields.
5. Upsert into `discovery_candidates` with status='pending'.
6. Record per-query yield stats back in QueryBankService.

Known place_ids are filtered against both the existing candidate rows and the
canonical properties table (via a later dedup service). For M3 we use the
candidate table alone; M6 (Dedup) will extend this when properties exist.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenError, NotFoundError
from app.integrations.google_places import (
    GooglePlacesClient,
    PlaceDetails,
    PlaceSearchResult,
)
from app.models.discovery import DiscoveryCandidate
from app.models.query_bank import QueryBank
from app.schemas.discovery import DiscoveryRunResult
from app.services.query_bank_service import QueryBankService
from app.services.source_service import SourceService

# Rough mapping from Google's place types to FastRecce property_type.
# First match wins. Fallback to the query's property_type if nothing matches.
_TYPE_PRIORITY: list[tuple[str, str]] = [
    ("lodging", "boutique_hotel"),
    ("resort_hotel", "resort"),
    ("restaurant", "restaurant"),
    ("cafe", "cafe"),
    ("bar", "club_lounge"),
    ("night_club", "club_lounge"),
    ("school", "school_campus"),
    ("university", "school_campus"),
    ("event_venue", "banquet_hall"),
    ("banquet_hall", "banquet_hall"),
    ("art_gallery", "theatre_studio"),
    ("movie_theater", "theatre_studio"),
    ("warehouse", "warehouse"),
    ("office_building", "office_space"),
    ("coworking_space", "coworking_space"),
]

_SOURCE_NAME = "google_places"


class DiscoveryService:
    def __init__(
        self,
        db: AsyncSession,
        google_client: GooglePlacesClient,
        source_service: SourceService,
        query_bank_service: QueryBankService,
    ) -> None:
        self.db = db
        self.google = google_client
        self.source_service = source_service
        self.query_bank_service = query_bank_service

    async def discover(
        self,
        cities: list[str] | None = None,
        property_types: list[str] | None = None,
        max_queries: int | None = None,
    ) -> DiscoveryRunResult:
        """Run a full discovery pass. Persists candidates, returns summary stats."""
        if not await self.source_service.is_source_allowed(_SOURCE_NAME):
            raise ForbiddenError(
                "Source 'google_places' is disabled or restricted. "
                "Enable it in the source registry before running discovery."
            )

        start = time.monotonic()
        queries = await self.query_bank_service.get_queries_for_discovery(
            cities=cities, property_types=property_types
        )
        if max_queries is not None:
            queries = queries[:max_queries]

        google_total = 0
        created = 0
        skipped_known = 0
        errors: list[str] = []

        for query in queries:
            try:
                results = await self.google.text_search(query.query_text)
            except Exception as exc:  # noqa: BLE001 — per-query isolation
                errors.append(f"text_search failed for '{query.query_text}': {exc}")
                continue

            google_total += len(results)
            new_for_query = 0

            known_ids = await self._find_known_place_ids(
                [r.place_id for r in results]
            )

            for result in results:
                if result.place_id in known_ids:
                    skipped_known += 1
                    continue

                try:
                    details = await self.google.get_place_details(result.place_id)
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        f"get_place_details failed for {result.place_id}: {exc}"
                    )
                    continue

                candidate = self._to_candidate(details, result, query)
                was_inserted = await self._upsert_candidate(candidate)
                if was_inserted:
                    created += 1
                    new_for_query += 1
                else:
                    skipped_known += 1

            try:
                await self.query_bank_service.record_run_result(
                    query_id=query.id,
                    results_count=len(results),
                    new_properties_count=new_for_query,
                )
            except NotFoundError:
                # Query was deleted mid-run; ignore.
                pass

        return DiscoveryRunResult(
            queries_executed=len(queries),
            google_results_total=google_total,
            candidates_created=created,
            candidates_skipped_known=skipped_known,
            errors=errors,
            duration_seconds=round(time.monotonic() - start, 3),
        )

    async def list_recent_candidates(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[DiscoveryCandidate]:
        stmt = select(DiscoveryCandidate).order_by(
            DiscoveryCandidate.discovered_at.desc()
        )
        if status is not None:
            stmt = stmt.where(DiscoveryCandidate.processing_status == status)
        stmt = stmt.limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_candidate(self, candidate_id: UUID) -> DiscoveryCandidate:
        candidate = await self.db.get(DiscoveryCandidate, candidate_id)
        if candidate is None:
            raise NotFoundError(f"Discovery candidate {candidate_id} not found")
        return candidate

    async def mark_processed(self, candidate_id: UUID) -> DiscoveryCandidate:
        from sqlalchemy.sql import func

        candidate = await self.get_candidate(candidate_id)
        candidate.processing_status = "processed"
        candidate.error_message = None
        candidate.processed_at = func.now()  # type: ignore[assignment]
        await self.db.flush()
        return candidate

    async def mark_failed(
        self, candidate_id: UUID, error: str
    ) -> DiscoveryCandidate:
        from sqlalchemy.sql import func

        candidate = await self.get_candidate(candidate_id)
        candidate.processing_status = "failed"
        candidate.error_message = error[:2000]
        candidate.processed_at = func.now()  # type: ignore[assignment]
        await self.db.flush()
        return candidate

    # --- Internals ---

    async def _find_known_place_ids(self, place_ids: list[str]) -> set[str]:
        if not place_ids:
            return set()
        stmt = select(DiscoveryCandidate.external_id).where(
            DiscoveryCandidate.source_name == _SOURCE_NAME,
            DiscoveryCandidate.external_id.in_(place_ids),
        )
        result = await self.db.execute(stmt)
        return {row[0] for row in result.all()}

    async def _upsert_candidate(self, data: dict[str, Any]) -> bool:
        """Insert a candidate. Returns True if a new row was created.

        Portable upsert: we filter known place_ids upstream, so a conflict on
        (source_name, external_id) is an edge case (concurrent run). When it
        does happen we swallow IntegrityError and treat it as a silent skip.
        """
        candidate = DiscoveryCandidate(**data)
        self.db.add(candidate)
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            return False
        return True

    def _to_candidate(
        self,
        details: PlaceDetails,
        search: PlaceSearchResult,
        query: QueryBank,
    ) -> dict[str, Any]:
        """Map Google result to a dict suitable for INSERT into discovery_candidates."""
        city, locality = _extract_city_locality(
            details.address_components, query.city, query.locality
        )
        return {
            "source_name": _SOURCE_NAME,
            "external_id": details.place_id,
            "query_id": query.id,
            "name": details.name or search.name,
            "address": details.address,
            "city": city,
            "locality": locality,
            "lat": details.lat,
            "lng": details.lng,
            "phone": details.phone,
            "website": details.website,
            "google_rating": details.rating,
            "google_review_count": details.review_count,
            "google_types": list(details.types),
            "property_type": _infer_property_type(details.types, query.property_type),
            "raw_result_json": {
                "search": search.raw,
                "details": details.raw,
            },
            "processing_status": "pending",
        }


# --- Module-private helpers ---


def _infer_property_type(google_types: list[str], fallback: str) -> str:
    """Map Google place types to FastRecce property_type. Fall back to the query's."""
    google_set = set(google_types)
    for key, mapped in _TYPE_PRIORITY:
        if key in google_set:
            return mapped
    return fallback


def _extract_city_locality(
    address_components: list[dict[str, Any]],
    fallback_city: str,
    fallback_locality: str | None,
) -> tuple[str, str | None]:
    """Pull city and locality from Google's addressComponents list.

    Google's `types` for Indian addresses commonly include:
      - 'locality' → city name (e.g. Mumbai)
      - 'sublocality_level_1' → neighborhood (e.g. Bandra West)
    """
    city = fallback_city
    locality = fallback_locality
    for comp in address_components:
        types = comp.get("types") or []
        name = comp.get("longText") or comp.get("shortText")
        if not name:
            continue
        if "locality" in types:
            city = name
        elif "sublocality_level_1" in types or "sublocality" in types:
            locality = name
    return city, locality

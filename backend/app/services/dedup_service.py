"""DedupService — M6. Multi-signal duplicate detection and merging.

Matching signals (cheapest first):
  1. Same google_place_id              → definite match (1.00)
  2. Same normalized phone (any contact) → 0.85
  3. Same canonical website domain      → 0.80
  4. Geo proximity + name similarity    → 0.30 + (similarity * 0.5)
  5. Image perceptual hash match        → +0.15 additive (deferred to a later module)

Confidence buckets:
  >= 0.90  → auto-merge (no human needed)
  0.50..0.90 → surface as duplicate warning for the reviewer
  <  0.50  → treated as distinct
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import cast
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import distinct, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import PropertyContact
from app.models.property import Property
from app.schemas.dedup import (
    BatchDedupResult,
    DedupDecision,
    DuplicateCandidate,
    MatchSignals,
    MergeResult,
)
from app.services.contact_service import normalize_phone
from app.services.property_service import PropertyService, normalize_name

AUTO_MERGE_THRESHOLD = 0.90
REVIEW_THRESHOLD = 0.50

GEO_RADIUS_METERS = 500
NAME_SIMILARITY_THRESHOLD = 0.30

class DedupService:
    def __init__(self, db: AsyncSession, property_service: PropertyService) -> None:
        self.db = db
        self.property_service = property_service

    # --- Public API ---

    async def check_candidate(
        self,
        *,
        google_place_id: str | None,
        canonical_name: str,
        city: str,
        lat: float | None,
        lng: float | None,
        website: str | None,
        phones: Iterable[str] = (),
        exclude_property_id: UUID | None = None,
    ) -> DedupDecision:
        """Run all signals against a hypothetical or just-created property.

        Returns a DedupDecision with confidence + matched candidates. Caller
        decides what to do (auto-merge / surface / ignore).
        """
        candidates_by_id: dict[UUID, MatchSignals] = {}

        # Signal 1: google_place_id (definite).
        if google_place_id:
            match = await self._match_by_place_id(google_place_id, exclude_property_id)
            if match is not None:
                candidates_by_id.setdefault(match.id, MatchSignals()).place_id_match = True

        # Signal 2: phone.
        for phone in phones:
            normalized = normalize_phone(phone)
            if normalized is None:
                continue
            for prop in await self._match_by_phone(normalized, exclude_property_id):
                candidates_by_id.setdefault(prop.id, MatchSignals()).phone_match = True

        # Signal 3: website domain.
        if website:
            domain = _domain_of(website)
            if domain:
                for prop in await self._match_by_website_domain(
                    domain, exclude_property_id
                ):
                    candidates_by_id.setdefault(
                        prop.id, MatchSignals()
                    ).website_match = True

        # Signal 4: geo + name similarity (PG path) or in-memory fallback.
        if lat is not None and lng is not None:
            normalized = normalize_name(canonical_name)
            geo_matches = await self._match_by_geo_and_name(
                lat=lat,
                lng=lng,
                normalized_name=normalized,
                city=city,
                exclude_property_id=exclude_property_id,
            )
            for prop_id, distance, name_sim in geo_matches:
                signals = candidates_by_id.setdefault(prop_id, MatchSignals())
                signals.distance_meters = distance
                signals.name_similarity = name_sim

        # Build DuplicateCandidate list with computed confidence.
        candidates: list[DuplicateCandidate] = []
        for prop_id, signals in candidates_by_id.items():
            prop = await self.db.get(Property, prop_id)
            if prop is None:
                continue
            confidence = _compute_confidence(signals)
            if confidence < REVIEW_THRESHOLD:
                continue
            candidates.append(
                DuplicateCandidate(
                    property_id=prop_id,
                    canonical_name=prop.canonical_name,
                    city=prop.city,
                    duplicate_confidence=confidence,
                    match_signals=signals,
                )
            )

        candidates.sort(key=lambda c: c.duplicate_confidence, reverse=True)

        if not candidates:
            return DedupDecision()

        top = candidates[0]
        return DedupDecision(
            is_duplicate=True,
            auto_merge=top.duplicate_confidence >= AUTO_MERGE_THRESHOLD,
            matched_property_id=top.property_id,
            confidence=top.duplicate_confidence,
            candidates=candidates,
        )

    async def find_duplicates_for_property(
        self, property_id: UUID
    ) -> list[DuplicateCandidate]:
        """Find potential duplicates for an existing property (dashboard view)."""
        prop = await self.property_service.get(property_id)
        phones = await self._phones_for_property(property_id)
        decision = await self.check_candidate(
            google_place_id=prop.google_place_id,
            canonical_name=prop.canonical_name,
            city=prop.city,
            lat=prop.lat,
            lng=prop.lng,
            website=prop.canonical_website,
            phones=phones,
            exclude_property_id=property_id,
        )
        return decision.candidates

    async def merge_properties(
        self,
        *,
        source_id: UUID,
        target_id: UUID,
        merged_by: UUID | None = None,
    ) -> MergeResult:
        """Merge `source` INTO `target`. Source becomes is_duplicate=true.

        Steps:
          1. Move all property_contacts from source -> target
             (skipping any (type, normalized_value) that already exists).
          2. Mark source.is_duplicate=true, source.duplicate_of=target_id,
             source.status='reviewed'.
          3. Re-elect canonical contacts on the target (delegated to ContactService).
        """
        if source_id == target_id:
            return MergeResult(
                source_id=source_id,
                target_id=target_id,
                status="skipped_self",
            )

        source = await self.property_service.get(source_id)
        await self.property_service.get(target_id)  # validates target exists

        # Pull all contacts upfront so we can compare-and-move.
        source_contacts = await self._contacts_for(source_id)
        target_keys = {
            (c.contact_type, c.normalized_value)
            for c in await self._contacts_for(target_id)
        }

        moved = 0
        already_existed = 0
        for contact in source_contacts:
            key = (contact.contact_type, contact.normalized_value)
            if key in target_keys:
                already_existed += 1
                # Drop the source row — target already has it; CASCADE will
                # delete it when the source property gets deleted later, but
                # we keep the source row marked as duplicate so we can audit.
                continue
            contact.property_id = target_id
            target_keys.add(key)
            moved += 1

        source.is_duplicate = True
        source.duplicate_of = target_id
        source.status = "reviewed"
        # Note who triggered the merge — useful for audit when M9 ships.
        if merged_by is not None:
            # No dedicated audit table yet — we just store nothing for now.
            # When users + property_changes tables land, log it there.
            pass

        await self.db.flush()

        return MergeResult(
            source_id=source_id,
            target_id=target_id,
            status="merged",
            contacts_moved=moved,
            contacts_already_existed=already_existed,
        )

    async def run_batch_dedup(
        self,
        *,
        city: str | None = None,
        confidence_threshold: float = REVIEW_THRESHOLD,
        auto_merge: bool = False,
    ) -> BatchDedupResult:
        """Pairwise sweep across non-duplicate properties, scoped by city.

        Cities partition the search space (we never compare a Mumbai property
        to a Pune one). Within a city, every non-duplicate property is checked
        once via check_candidate(); ties are broken by created_at ASC (the
        older row is the merge target).
        """
        start = time.monotonic()
        stmt = select(Property).where(Property.is_duplicate.is_(False))
        if city is not None:
            stmt = stmt.where(Property.city == city)
        stmt = stmt.order_by(Property.created_at.asc())
        result = await self.db.execute(stmt)
        properties = list(result.scalars().all())

        seen_pairs: set[tuple[UUID, UUID]] = set()
        merged = 0
        flagged = 0
        pairs: list[tuple[UUID, UUID, float]] = []

        for prop in properties:
            decision = await self.find_duplicates_for_property(prop.id)
            for cand in decision:
                if cand.duplicate_confidence < confidence_threshold:
                    continue

                # Order pair canonically (older property is target).
                older_id = prop.id  # because we ordered ascending and iterate in that order
                newer_id = cand.property_id
                pair_key = tuple(sorted([str(older_id), str(newer_id)]))
                pair_tuple = (UUID(pair_key[0]), UUID(pair_key[1]))
                if pair_tuple in seen_pairs:
                    continue
                seen_pairs.add(pair_tuple)

                pairs.append((older_id, newer_id, cand.duplicate_confidence))
                if auto_merge and cand.duplicate_confidence >= AUTO_MERGE_THRESHOLD:
                    await self.merge_properties(
                        source_id=newer_id, target_id=older_id
                    )
                    merged += 1
                else:
                    flagged += 1

        return BatchDedupResult(
            pairs_compared=len(properties),
            auto_merged=merged,
            flagged_for_review=flagged,
            duration_seconds=round(time.monotonic() - start, 3),
            pairs=pairs,
        )

    # --- Internals ---

    async def _match_by_place_id(
        self, place_id: str, exclude_property_id: UUID | None
    ) -> Property | None:
        stmt = select(Property).where(
            Property.google_place_id == place_id,
            Property.is_duplicate.is_(False),
        )
        if exclude_property_id is not None:
            stmt = stmt.where(Property.id != exclude_property_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _match_by_phone(
        self, normalized_phone: str, exclude_property_id: UUID | None
    ) -> list[Property]:
        # Find any property that owns a contact with the same normalized_value.
        property_ids_stmt = (
            select(distinct(PropertyContact.property_id))
            .where(
                PropertyContact.contact_type == "phone",
                PropertyContact.normalized_value == normalized_phone,
            )
        )
        ids = list((await self.db.execute(property_ids_stmt)).scalars().all())
        if not ids:
            return []

        stmt = select(Property).where(
            Property.id.in_(ids), Property.is_duplicate.is_(False)
        )
        if exclude_property_id is not None:
            stmt = stmt.where(Property.id != exclude_property_id)
        return list((await self.db.execute(stmt)).scalars().all())

    async def _match_by_website_domain(
        self, domain: str, exclude_property_id: UUID | None
    ) -> list[Property]:
        # Match properties whose canonical_website contains the domain (sub_paths ok).
        like_pattern = f"%{domain}%"
        stmt = select(Property).where(
            Property.canonical_website.like(like_pattern),
            Property.is_duplicate.is_(False),
        )
        if exclude_property_id is not None:
            stmt = stmt.where(Property.id != exclude_property_id)
        return list((await self.db.execute(stmt)).scalars().all())

    async def _match_by_geo_and_name(
        self,
        *,
        lat: float,
        lng: float,
        normalized_name: str,
        city: str,
        exclude_property_id: UUID | None,
    ) -> list[tuple[UUID, float, float]]:
        """Return [(property_id, distance_meters, name_similarity)].

        On PostgreSQL: uses ST_DWithin + similarity() in a single query.
        On SQLite (tests): falls back to comparing every property in the
        same city in Python.
        """
        dialect = self.db.bind.dialect.name if self.db.bind else "postgresql"

        if dialect == "postgresql":
            return await self._geo_name_pg(
                lat=lat,
                lng=lng,
                normalized_name=normalized_name,
                exclude_property_id=exclude_property_id,
            )
        return await self._geo_name_python(
            lat=lat,
            lng=lng,
            normalized_name=normalized_name,
            city=city,
            exclude_property_id=exclude_property_id,
        )

    async def _geo_name_pg(
        self,
        *,
        lat: float,
        lng: float,
        normalized_name: str,
        exclude_property_id: UUID | None,
    ) -> list[tuple[UUID, float, float]]:
        exclude_clause = "AND id != :exclude_id" if exclude_property_id else ""
        sql = text(
            f"""
            SELECT
                id,
                ST_Distance(location, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography) AS distance_meters,
                similarity(normalized_name, :normalized_name) AS name_similarity
            FROM properties
            WHERE
                location IS NOT NULL
                AND is_duplicate = false
                AND ST_DWithin(
                    location,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                    :radius
                )
                AND similarity(normalized_name, :normalized_name) > :name_threshold
                {exclude_clause}
            ORDER BY name_similarity DESC, distance_meters ASC
            LIMIT 25
            """
        )
        params: dict[str, object] = {
            "lat": lat,
            "lng": lng,
            "normalized_name": normalized_name,
            "radius": GEO_RADIUS_METERS,
            "name_threshold": NAME_SIMILARITY_THRESHOLD,
        }
        if exclude_property_id is not None:
            params["exclude_id"] = str(exclude_property_id)

        result = await self.db.execute(sql, params)
        rows = result.all()
        return [(cast(UUID, r[0]), float(r[1]), float(r[2])) for r in rows]

    async def _geo_name_python(
        self,
        *,
        lat: float,
        lng: float,
        normalized_name: str,
        city: str,
        exclude_property_id: UUID | None,
    ) -> list[tuple[UUID, float, float]]:
        # Tests: linear scan within the city. Acceptable for small datasets.
        stmt = select(Property).where(
            Property.city == city,
            Property.is_duplicate.is_(False),
            Property.lat.is_not(None),
            Property.lng.is_not(None),
        )
        if exclude_property_id is not None:
            stmt = stmt.where(Property.id != exclude_property_id)
        candidates = (await self.db.execute(stmt)).scalars().all()

        results: list[tuple[UUID, float, float]] = []
        for prop in candidates:
            assert prop.lat is not None and prop.lng is not None  # narrowed above
            distance = _haversine_meters(lat, lng, prop.lat, prop.lng)
            if distance > GEO_RADIUS_METERS:
                continue
            similarity = _python_similarity(normalized_name, prop.normalized_name)
            if similarity <= NAME_SIMILARITY_THRESHOLD:
                continue
            results.append((prop.id, distance, similarity))

        results.sort(key=lambda r: (-r[2], r[1]))
        return results

    async def _contacts_for(self, property_id: UUID) -> list[PropertyContact]:
        stmt = select(PropertyContact).where(
            PropertyContact.property_id == property_id
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def _phones_for_property(self, property_id: UUID) -> list[str]:
        stmt = select(PropertyContact.normalized_value).where(
            PropertyContact.property_id == property_id,
            PropertyContact.contact_type == "phone",
        )
        return list((await self.db.execute(stmt)).scalars().all())


# --- Module helpers ---


def _domain_of(url: str) -> str:
    """Return the registrable domain from a URL.

    'https://www.silvanus.in/contact' -> 'silvanus.in'
    """
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    netloc = urlparse(url).netloc.lower()
    return netloc.removeprefix("www.")


def _compute_confidence(signals: MatchSignals) -> float:
    """Combine per-signal flags into a 0-1 dedup confidence."""
    score = 0.0
    if signals.place_id_match:
        return 1.0  # definite
    if signals.phone_match:
        score = max(score, 0.85)
    if signals.website_match:
        score = max(score, 0.80)
    if signals.distance_meters is not None and signals.name_similarity is not None:
        # Closer + more similar = higher score; max 0.80 from this signal alone.
        # Distance contributes inversely (0m -> 0.30, 500m -> 0).
        distance_factor = max(0.0, 1.0 - signals.distance_meters / GEO_RADIUS_METERS)
        geo_score = 0.30 * distance_factor + 0.50 * signals.name_similarity
        score = max(score, geo_score)
    if signals.image_hash_match:
        # Additive bonus when we have at least one other signal.
        if score > 0:
            score = min(1.0, score + 0.15)
    return min(1.0, score)


def _haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    import math

    radius_m = 6_371_000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_m * c


def _python_similarity(a: str, b: str) -> float:
    """Approximation of pg_trgm.similarity() via SequenceMatcher.

    Not bit-identical to PostgreSQL's trigram similarity, but produces values
    in the same 0-1 range and the same ordering for common cases.
    """
    from difflib import SequenceMatcher

    return SequenceMatcher(None, a, b).ratio()



"""PropertyService — canonical-entity CRUD used across the pipeline.

Scope for now: just what M5 needs to promote a discovery candidate into a
property record. Full read/list/review APIs come with M9 (dashboard).
Dedup is M6's concern — for now every candidate becomes a new property.
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.property import Property
from app.schemas.property import PropertyUpsertFromCandidate


class PropertyService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, property_id: UUID) -> Property:
        prop = await self.db.get(Property, property_id)
        if prop is None:
            raise NotFoundError(f"Property {property_id} not found")
        return prop

    async def find_by_google_place_id(self, place_id: str) -> Property | None:
        stmt = select(Property).where(Property.google_place_id == place_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_from_candidate(
        self, data: PropertyUpsertFromCandidate
    ) -> Property:
        """Create-or-update a property based on a discovery candidate.

        Dedup is intentionally minimal here — only an exact google_place_id
        match. M6 will replace this with multi-signal dedup (phone, geo,
        name similarity, image hash).
        """
        existing = (
            await self.find_by_google_place_id(data.google_place_id)
            if data.google_place_id
            else None
        )

        if existing is not None:
            self._apply_candidate_fields(existing, data)
            await self.db.flush()
            await self.db.refresh(existing)
            return existing

        prop = Property(
            canonical_name=data.canonical_name,
            normalized_name=normalize_name(data.canonical_name),
            normalized_address=None,
            city=data.city,
            locality=data.locality,
            state=data.state,
            pincode=data.pincode,
            lat=data.lat,
            lng=data.lng,
            location=_geography_point(data.lat, data.lng),
            property_type=data.property_type,
            status="new",
            canonical_website=data.website,
            google_place_id=data.google_place_id,
            google_rating=data.google_rating,
            google_review_count=data.google_review_count,
            features_json=data.features_json,
        )
        self.db.add(prop)
        await self.db.flush()
        await self.db.refresh(prop)
        return prop

    async def update_canonical_contacts(
        self,
        property_id: UUID,
        *,
        phone: str | None = None,
        email: str | None = None,
        website: str | None = None,
    ) -> Property:
        prop = await self.get(property_id)
        if phone is not None:
            prop.canonical_phone = phone
        if email is not None:
            prop.canonical_email = email
        if website is not None:
            prop.canonical_website = website
        await self.db.flush()
        await self.db.refresh(prop)
        return prop

    async def merge_features(
        self, property_id: UUID, features: dict[str, object]
    ) -> Property:
        """Merge a CrawlResult's features dict into properties.features_json."""
        prop = await self.get(property_id)
        merged = {**(prop.features_json or {}), **features}
        prop.features_json = merged
        await self.db.flush()
        await self.db.refresh(prop)
        return prop

    # --- Internals ---

    def _apply_candidate_fields(
        self, prop: Property, data: PropertyUpsertFromCandidate
    ) -> None:
        # Update only the fields the candidate is authoritative for.
        if data.canonical_name and prop.canonical_name != data.canonical_name:
            prop.canonical_name = data.canonical_name
            prop.normalized_name = normalize_name(data.canonical_name)
        if data.lat is not None:
            prop.lat = data.lat
        if data.lng is not None:
            prop.lng = data.lng
        if data.lat is not None and data.lng is not None:
            prop.location = _geography_point(data.lat, data.lng)
        if data.locality:
            prop.locality = data.locality
        if data.state:
            prop.state = data.state
        if data.pincode:
            prop.pincode = data.pincode
        if data.google_rating is not None:
            prop.google_rating = data.google_rating
        if data.google_review_count is not None:
            prop.google_review_count = data.google_review_count
        if data.website and not prop.canonical_website:
            prop.canonical_website = data.website
        if data.features_json:
            prop.features_json = {**(prop.features_json or {}), **data.features_json}


# --- Module helpers ---

_NAME_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_NAME_WS_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    'The Oberoi, Mumbai' -> 'the oberoi mumbai'
    Used for dedup matching by M6. Stored on the row to avoid recomputing.
    """
    cleaned = _NAME_PUNCT_RE.sub(" ", name.lower())
    return _NAME_WS_RE.sub(" ", cleaned).strip()


def _geography_point(lat: float | None, lng: float | None) -> str | None:
    """Build a WKT POINT for the GEOGRAPHY column, or None on missing coords.

    PostGIS accepts the WKT form 'POINT(lng lat)' (note the order).
    On SQLite (test mode), the column is a String so we just store the WKT
    and ignore spatial semantics.
    """
    if lat is None or lng is None:
        return None
    return f"SRID=4326;POINT({lng} {lat})"

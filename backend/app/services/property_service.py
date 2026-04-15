"""PropertyService — canonical-entity CRUD used across the pipeline.

Scope for now: just what M5 needs to promote a discovery candidate into a
property record. Full read/list/review APIs come with M9 (dashboard).
Dedup is M6's concern — for now every candidate becomes a new property.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.contact import DoNotContact, PropertyContact
from app.models.outreach import OutreachQueue
from app.models.property import Property
from app.schemas.property import PropertyUpsertFromCandidate
from app.schemas.review import ReviewRequest, ReviewResponse


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

    # --- Dashboard read (M9) ---

    async def list_for_dashboard(
        self,
        *,
        city: str | None = None,
        property_types: list[str] | None = None,
        statuses: list[str] | None = None,
        min_score: float | None = None,
        max_score: float | None = None,
        has_phone: bool | None = None,
        has_email: bool | None = None,
        include_duplicates: bool = False,
        search: str | None = None,
        sort: str = "relevance_score_desc",
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Property], int]:
        """List properties for the Lead Queue. Returns (items, total_count)."""
        filters = []
        if city is not None:
            filters.append(Property.city == city)
        if property_types:
            filters.append(Property.property_type.in_(property_types))
        if statuses:
            filters.append(Property.status.in_(statuses))
        if min_score is not None:
            filters.append(Property.relevance_score >= min_score)
        if max_score is not None:
            filters.append(Property.relevance_score <= max_score)
        if has_phone is True:
            filters.append(Property.canonical_phone.is_not(None))
        elif has_phone is False:
            filters.append(Property.canonical_phone.is_(None))
        if has_email is True:
            filters.append(Property.canonical_email.is_not(None))
        elif has_email is False:
            filters.append(Property.canonical_email.is_(None))
        if not include_duplicates:
            filters.append(Property.is_duplicate.is_(False))
        if search:
            pattern = f"%{search.lower()}%"
            filters.append(
                (func.lower(Property.canonical_name).like(pattern))
                | (func.lower(Property.locality).like(pattern))
            )

        # Count first.
        count_stmt = select(func.count(Property.id))
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = (await self.db.execute(count_stmt)).scalar_one()

        # Page.
        stmt = select(Property)
        if filters:
            stmt = stmt.where(*filters)
        stmt = _apply_sort(stmt, sort).offset(offset).limit(limit)
        rows = list((await self.db.execute(stmt)).scalars().all())
        return rows, int(total)

    async def get_detail(self, property_id: UUID) -> tuple[Property, list[PropertyContact], OutreachQueue | None]:
        """Load the property + related rows the dashboard detail view needs."""
        prop = await self.get(property_id)

        contacts_stmt = (
            select(PropertyContact)
            .where(PropertyContact.property_id == property_id)
            .order_by(PropertyContact.confidence.desc())
        )
        contacts = list((await self.db.execute(contacts_stmt)).scalars().all())

        outreach_stmt = select(OutreachQueue).where(OutreachQueue.property_id == property_id)
        outreach = (await self.db.execute(outreach_stmt)).scalar_one_or_none()

        return prop, contacts, outreach

    # --- Review actions (M9) ---

    async def review(
        self, property_id: UUID, request: ReviewRequest, reviewer_id: UUID | None = None
    ) -> ReviewResponse:
        """Apply a review action. Enforces status transitions + side effects."""
        prop = await self.get(property_id)
        action = request.action

        if action == "approve":
            _assert_transition(prop.status, {"new", "reviewed", "rejected"}, action)
            prop.status = "approved"
            created = await self._ensure_outreach_entry(prop, reviewer_id)
            return ReviewResponse(
                property_id=property_id,
                status=prop.status,
                action_applied=action,
                outreach_created=created,
            )

        if action == "reject":
            _assert_transition(
                prop.status, {"new", "reviewed", "approved"}, action
            )
            prop.status = "rejected"
            return ReviewResponse(
                property_id=property_id, status=prop.status, action_applied=action
            )

        if action == "reopen":
            _assert_transition(prop.status, {"rejected", "do_not_contact"}, action)
            prop.status = "new"
            return ReviewResponse(
                property_id=property_id, status=prop.status, action_applied=action
            )

        if action == "do_not_contact":
            prop.status = "do_not_contact"
            added = await self._blocklist_contacts(property_id, request.notes or "dnc via review", reviewer_id)
            return ReviewResponse(
                property_id=property_id,
                status=prop.status,
                action_applied=action,
                dnc_entries_added=added,
            )

        if action == "merge":
            if request.merge_into_id is None:
                raise ValidationError("merge action requires merge_into_id")
            if request.merge_into_id == property_id:
                raise ValidationError("cannot merge a property into itself")
            # Ensure target exists. Actual contact-move is DedupService's job.
            await self.get(request.merge_into_id)
            prop.status = "reviewed"
            prop.is_duplicate = True
            prop.duplicate_of = request.merge_into_id
            return ReviewResponse(
                property_id=property_id,
                status=prop.status,
                action_applied=action,
                merged_into_id=request.merge_into_id,
            )

        raise ValidationError(f"unsupported review action: {action}")

    # --- Internal helpers ---

    async def _ensure_outreach_entry(
        self, prop: Property, reviewer_id: UUID | None
    ) -> bool:
        """Create an outreach queue entry for a newly-approved property."""
        existing_stmt = select(OutreachQueue).where(OutreachQueue.property_id == prop.id)
        existing = (await self.db.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            return False

        priority = int(round((prop.relevance_score or 0.5) * 100))
        outreach = OutreachQueue(
            property_id=prop.id,
            status="pending",
            priority=max(1, min(100, priority)),
            assigned_to=reviewer_id,
        )
        self.db.add(outreach)
        await self.db.flush()
        return True

    async def _blocklist_contacts(
        self, property_id: UUID, reason: str, added_by: UUID | None
    ) -> int:
        """Copy every contact belonging to the property into do_not_contact."""
        stmt = select(PropertyContact).where(PropertyContact.property_id == property_id)
        contacts = list((await self.db.execute(stmt)).scalars().all())

        added = 0
        for contact in contacts:
            if contact.contact_type not in ("phone", "email", "whatsapp"):
                continue
            dnc_stmt = select(DoNotContact).where(
                DoNotContact.contact_type == contact.contact_type,
                DoNotContact.contact_value == contact.normalized_value,
            )
            if (await self.db.execute(dnc_stmt)).scalar_one_or_none() is not None:
                continue
            self.db.add(
                DoNotContact(
                    contact_type=contact.contact_type,
                    contact_value=contact.normalized_value,
                    reason=reason,
                    added_by=added_by,
                )
            )
            added += 1
        await self.db.flush()
        return added

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


def _apply_sort(stmt: Any, sort: str) -> Any:
    match sort:
        case "relevance_score_desc":
            return stmt.order_by(
                Property.relevance_score.desc().nulls_last(),
                Property.created_at.desc(),
            )
        case "relevance_score_asc":
            return stmt.order_by(
                Property.relevance_score.asc().nulls_first(),
                Property.created_at.desc(),
            )
        case "created_at_desc":
            return stmt.order_by(Property.created_at.desc())
        case "created_at_asc":
            return stmt.order_by(Property.created_at.asc())
        case "canonical_name_asc":
            return stmt.order_by(Property.canonical_name.asc())
        case _:
            return stmt.order_by(Property.created_at.desc())


def _assert_transition(current: str, allowed_from: set[str], action: str) -> None:
    """Raise ConflictError if `action` is not valid from the current status."""
    if current not in allowed_from:
        raise ConflictError(
            f"cannot {action} a property with status '{current}' "
            f"(expected one of {sorted(allowed_from)})"
        )

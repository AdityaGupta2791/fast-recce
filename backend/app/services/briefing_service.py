"""BriefingService — M8. Generates 2-3 sentence operational briefs per property.

Persists to properties.short_brief and properties.brief_generated_at.
Uses LLMClient with a template fallback so Gemini outages never block
the pipeline.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.llm import LLMClient
from app.models.property import Property
from app.schemas.briefing import BatchBriefResult, BriefResult
from app.services.contact_service import ContactService
from app.services.property_service import PropertyService


class BriefingService:
    def __init__(
        self,
        db: AsyncSession,
        llm_client: LLMClient,
        property_service: PropertyService,
        contact_service: ContactService,
    ) -> None:
        self.db = db
        self.llm = llm_client
        self.property_service = property_service
        self.contact_service = contact_service

    async def generate_brief(
        self, property_id: UUID, *, force: bool = False
    ) -> BriefResult:
        """Generate (or regenerate) a brief for a single property.

        If `force=False` and the property already has a brief that was generated
        after the last update, we skip (cache behavior).
        """
        prop = await self.property_service.get(property_id)

        if not force and _brief_still_fresh(prop):
            assert prop.short_brief is not None  # guaranteed by _brief_still_fresh
            return BriefResult(
                property_id=property_id,
                brief=prop.short_brief,
                source="cached",
                regenerated=False,
            )

        regenerated = prop.short_brief is not None
        features = prop.features_json or {}
        contacts = await self.contact_service.get_contacts_for_property(property_id)

        result = await self.llm.generate_brief(
            property_name=prop.canonical_name,
            city=prop.city,
            locality=prop.locality,
            property_type=prop.property_type,
            description=features.get("description"),
            amenities=list(features.get("amenities") or []),
            feature_tags=list(features.get("feature_tags") or []),
            top_score_factors=_top_score_factors(prop.score_reason_json),
            contact_summary=_contact_summary(contacts),
        )

        prop.short_brief = result.text
        prop.brief_generated_at = datetime.now(UTC)
        await self.db.flush()

        return BriefResult(
            property_id=property_id,
            brief=result.text,
            source=result.source,  # type: ignore[arg-type]
            regenerated=regenerated,
        )

    async def generate_batch(
        self,
        *,
        limit: int | None = None,
        only_unbriefed: bool = True,
        per_property_delay_seconds: float = 0.0,
    ) -> BatchBriefResult:
        """Generate briefs for every (un)briefed, non-duplicate property.

        `per_property_delay_seconds` throttles between properties to stay
        under the Gemini free-tier RPM limit.
        """
        start = time.monotonic()

        stmt = select(Property).where(Property.is_duplicate.is_(False))
        if only_unbriefed:
            stmt = stmt.where(Property.brief_generated_at.is_(None))
        stmt = stmt.order_by(
            Property.relevance_score.desc().nulls_last(), Property.created_at.asc()
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        properties = list((await self.db.execute(stmt)).scalars().all())

        generated = 0
        skipped = 0
        failed = 0
        fallbacks = 0

        for i, prop in enumerate(properties):
            if i > 0 and per_property_delay_seconds > 0:
                await asyncio.sleep(per_property_delay_seconds)
            try:
                result = await self.generate_brief(prop.id, force=not only_unbriefed)
            except Exception as exc:  # noqa: BLE001 — per-property isolation
                failed += 1
                print(f"  brief failed for {prop.id}: {exc}")
                continue

            if result.source == "cached":
                skipped += 1
                continue

            generated += 1
            if result.source == "fallback":
                fallbacks += 1

        return BatchBriefResult(
            generated=generated,
            skipped_unchanged=skipped,
            failed=failed,
            llm_fallbacks_used=fallbacks,
            duration_seconds=round(time.monotonic() - start, 3),
        )


# --- Module-private helpers ---


def _brief_still_fresh(prop: Property) -> bool:
    """Cache hit: we already have a brief and nothing relevant changed since."""
    if prop.short_brief is None or prop.brief_generated_at is None:
        return False
    # SQLite (test) loses tz info; PostgreSQL keeps it. Normalize to compare.
    updated = _naive(prop.updated_at)
    generated = _naive(prop.brief_generated_at)
    if updated > generated:
        return False
    return True


def _naive(dt: datetime) -> datetime:
    """Strip tzinfo so naive (SQLite) and aware (Postgres) values compare."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _top_score_factors(score_reason: dict[str, Any] | None) -> list[str]:
    """Pull the 3 highest-weighted sub_scores from score_reason_json."""
    if not score_reason:
        return []
    sub_scores = score_reason.get("sub_scores") or []
    if not isinstance(sub_scores, list):
        return []

    scored: list[tuple[float, str]] = []
    for s in sub_scores:
        if not isinstance(s, dict):
            continue
        try:
            contribution = float(s.get("value", 0)) * float(s.get("weight", 0))
        except (TypeError, ValueError):
            continue
        name = s.get("name")
        if isinstance(name, str):
            scored.append((contribution, name))

    scored.sort(reverse=True)
    return [name for _, name in scored[:3]]


def _contact_summary(contacts: list[Any]) -> str:
    """Short human-readable summary of contactability for the prompt."""
    if not contacts:
        return "no contacts yet"
    types = {c.contact_type for c in contacts}
    has_whatsapp = "whatsapp" in types
    has_phone = "phone" in types
    has_email = "email" in types
    has_website = "website" in types

    parts: list[str] = []
    if has_phone:
        parts.append("phone")
    if has_email:
        parts.append("email")
    if has_whatsapp:
        parts.append("WhatsApp")
    if has_website and not has_email:
        parts.append("website")
    return ", ".join(parts) if parts else "form/social only"

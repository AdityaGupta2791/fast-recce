"""Unit tests for BriefingService (M8)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.llm import LLMTextResult
from app.schemas.property import PropertyUpsertFromCandidate
from app.services.briefing_service import BriefingService
from app.services.contact_service import ContactService
from app.services.property_service import PropertyService

pytestmark = pytest.mark.asyncio


class FakeLLMClient:
    def __init__(self, text: str = "Sample LLM brief text.", source: str = "llm") -> None:
        self.text = text
        self.source = source
        self.calls = 0

    async def generate_brief(self, **_kwargs: object) -> LLMTextResult:
        self.calls += 1
        return LLMTextResult(text=self.text, source=self.source)


async def _make_property(
    db: AsyncSession,
    name: str = "Sunset Villa",
    **kwargs: object,
) -> uuid.UUID:
    service = PropertyService(db=db)
    prop = await service.upsert_from_candidate(
        PropertyUpsertFromCandidate(
            candidate_id=uuid.uuid4(),
            canonical_name=name,
            city="Alibaug",
            locality="Nagaon",
            lat=18.6414,
            lng=72.8722,
            property_type="villa",
            google_place_id=f"pid_{uuid.uuid4().hex[:6]}",
            website="https://sunset.com",
            features_json={
                "amenities": ["pool", "lawn"],
                "feature_tags": ["heritage"],
                "description": "Heritage villa with pool and lawn.",
            },
        )
    )
    return prop.id


def _service(db: AsyncSession, llm: FakeLLMClient) -> BriefingService:
    ps = PropertyService(db=db)
    cs = ContactService(db=db, property_service=ps)
    return BriefingService(db=db, llm_client=llm, property_service=ps, contact_service=cs)  # type: ignore[arg-type]


async def test_generate_brief_writes_to_property(db_session: AsyncSession) -> None:
    prop_id = await _make_property(db_session)
    llm = FakeLLMClient(text="A heritage villa in Alibaug with pool. Good shoot fit.")
    service = _service(db_session, llm)

    result = await service.generate_brief(prop_id)

    assert result.brief == "A heritage villa in Alibaug with pool. Good shoot fit."
    assert result.source == "llm"
    assert result.regenerated is False
    assert llm.calls == 1

    # Verify persisted.
    prop = await PropertyService(db=db_session).get(prop_id)
    assert prop.short_brief == result.brief
    assert prop.brief_generated_at is not None


async def test_cached_brief_returned_without_llm_call(db_session: AsyncSession) -> None:
    prop_id = await _make_property(db_session)
    llm = FakeLLMClient()
    service = _service(db_session, llm)

    first = await service.generate_brief(prop_id)
    second = await service.generate_brief(prop_id)  # should be cached

    assert first.source == "llm"
    assert second.source == "cached"
    assert second.brief == first.brief
    assert llm.calls == 1  # only one actual call


async def test_force_regeneration_overrides_cache(db_session: AsyncSession) -> None:
    prop_id = await _make_property(db_session)
    llm = FakeLLMClient()
    service = _service(db_session, llm)

    first = await service.generate_brief(prop_id)
    assert first.regenerated is False

    llm.text = "Updated brief text."
    second = await service.generate_brief(prop_id, force=True)

    assert second.source == "llm"
    assert second.regenerated is True
    assert second.brief == "Updated brief text."
    assert llm.calls == 2


async def test_cache_invalidated_when_property_updated(
    db_session: AsyncSession,
) -> None:
    prop_id = await _make_property(db_session)
    llm = FakeLLMClient()
    service = _service(db_session, llm)

    await service.generate_brief(prop_id)
    # Simulate a downstream change bumping updated_at AFTER brief_generated_at.
    prop = await PropertyService(db=db_session).get(prop_id)
    prop.updated_at = datetime.now(UTC) + timedelta(minutes=1)
    await db_session.flush()

    llm.text = "Regenerated brief text."
    result = await service.generate_brief(prop_id)

    assert result.source == "llm"
    assert result.regenerated is True


async def test_fallback_source_propagates(db_session: AsyncSession) -> None:
    prop_id = await _make_property(db_session)
    llm = FakeLLMClient(
        text="Sunset Villa is a villa in Alibaug with pool, lawn.",
        source="fallback",
    )
    service = _service(db_session, llm)

    result = await service.generate_brief(prop_id)
    assert result.source == "fallback"


async def test_generate_batch_only_unbriefed(db_session: AsyncSession) -> None:
    briefed_id = await _make_property(db_session, name="Already Briefed")
    await _make_property(db_session, name="Needs Brief")

    llm = FakeLLMClient()
    service = _service(db_session, llm)

    # Brief the first one first.
    await service.generate_brief(briefed_id)
    assert llm.calls == 1

    # Batch should only touch the unbriefed one.
    result = await service.generate_batch(only_unbriefed=True)
    assert result.generated == 1
    assert result.failed == 0
    assert llm.calls == 2  # +1 for the new brief


async def test_generate_batch_rescore_mode_regenerates_all(
    db_session: AsyncSession,
) -> None:
    a_id = await _make_property(db_session, name="A")
    await _make_property(db_session, name="B")

    llm = FakeLLMClient()
    service = _service(db_session, llm)

    await service.generate_brief(a_id)  # gives A a brief
    assert llm.calls == 1

    result = await service.generate_batch(only_unbriefed=False)
    # Force=True path through generate_brief: both get (re)generated.
    assert result.generated == 2
    assert llm.calls == 3  # 1 original + 2 in batch


async def test_generate_batch_tracks_fallbacks(db_session: AsyncSession) -> None:
    await _make_property(db_session, name="A")
    await _make_property(db_session, name="B")

    llm = FakeLLMClient(source="fallback")
    service = _service(db_session, llm)

    result = await service.generate_batch()
    assert result.generated == 2
    assert result.llm_fallbacks_used == 2


async def test_fallback_template_shape() -> None:
    """The fallback helper on LLMClient produces an operational template."""
    from app.integrations.llm import LLMClient

    text = LLMClient._brief_fallback(
        property_name="Sunset Villa",
        property_type="heritage_home",
        city="Alibaug",
        amenities=["pool", "lawn", "terrace"],
        contact_summary="phone, email",
    )
    assert "Sunset Villa" in text
    assert "Alibaug" in text
    assert "pool" in text
    assert "phone" in text
    # 2-3 sentences.
    assert text.count(".") >= 2

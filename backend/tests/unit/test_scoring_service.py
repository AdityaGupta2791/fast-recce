"""Unit tests for ScoringService (M7)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.llm import LLMScoreResult
from app.schemas.crawl import ExtractedContact
from app.schemas.property import PropertyUpsertFromCandidate
from app.services.contact_service import ContactService
from app.services.property_service import PropertyService
from app.services.scoring_service import ScoringService

pytestmark = pytest.mark.asyncio


class FakeLLMClient:
    """Deterministic stand-in for LLMClient.

    Default: returns score=0.7 for everything. Override per-method if needed.
    """

    def __init__(
        self,
        shoot_fit: float = 0.7,
        visual: float = 0.6,
        source: str = "llm",
    ) -> None:
        self.shoot_fit_value = shoot_fit
        self.visual_value = visual
        self.source = source
        self.shoot_fit_calls = 0
        self.visual_calls = 0

    async def assess_shoot_fit(self, **_kwargs: object) -> LLMScoreResult:
        self.shoot_fit_calls += 1
        return LLMScoreResult(
            score=self.shoot_fit_value,
            reasoning="mocked",
            source=self.source,
        )

    async def assess_visual_uniqueness(self, **_kwargs: object) -> LLMScoreResult:
        self.visual_calls += 1
        return LLMScoreResult(
            score=self.visual_value,
            reasoning="mocked",
            source=self.source,
        )


async def _make_property(
    db: AsyncSession,
    name: str = "Sunset Villa",
    city: str = "Alibaug",
    property_type: str = "villa",
    website: str | None = "https://sunset.com",
    reviews: int | None = 50,
    amenities: list[str] | None = None,
    feature_tags: list[str] | None = None,
    description: str | None = None,
) -> str:
    service = PropertyService(db=db)
    prop = await service.upsert_from_candidate(
        PropertyUpsertFromCandidate(
            candidate_id=__import__("uuid").uuid4(),
            canonical_name=name,
            city=city,
            locality="Nagaon",
            lat=18.6414,
            lng=72.8722,
            property_type=property_type,  # type: ignore[arg-type]
            google_place_id=f"pid_{name[:5]}_{__import__('uuid').uuid4().hex[:4]}",
            google_review_count=reviews,
            google_rating=4.5,
            website=website,
            features_json={
                "amenities": amenities or [],
                "feature_tags": feature_tags or [],
                "description": description,
            },
        )
    )
    return prop.id


def _make_service(
    db: AsyncSession,
    llm: FakeLLMClient,
) -> ScoringService:
    property_service = PropertyService(db=db)
    contact_service = ContactService(db=db, property_service=property_service)
    return ScoringService(
        db=db,
        llm_client=llm,  # type: ignore[arg-type]
        property_service=property_service,
        contact_service=contact_service,
    )


async def test_score_property_applies_formula(db_session: AsyncSession) -> None:
    prop_id = await _make_property(db_session)
    llm = FakeLLMClient(shoot_fit=0.8, visual=0.6)
    service = _make_service(db_session, llm)

    result = await service.score_property(prop_id)

    # Verify formula: weighted sum of 8 sub-scores.
    computed = sum(s.value * s.weight for s in result.sub_scores)
    assert result.relevance_score == pytest.approx(computed, abs=1e-6)

    names = {s.name for s in result.sub_scores}
    assert names == {
        "type_fit",
        "shoot_fit",
        "visual_uniqueness",
        "location_demand",
        "contact_completeness",
        "website_quality",
        "activity_recency",
        "ease_of_outreach",
    }


async def test_score_property_calls_llm_twice(db_session: AsyncSession) -> None:
    prop_id = await _make_property(db_session)
    llm = FakeLLMClient()
    service = _make_service(db_session, llm)

    await service.score_property(prop_id)
    assert llm.shoot_fit_calls == 1
    assert llm.visual_calls == 1


async def test_score_persists_to_db(db_session: AsyncSession) -> None:
    prop_id = await _make_property(db_session)
    service = _make_service(db_session, FakeLLMClient())

    result = await service.score_property(prop_id)

    # Re-read the property and check DB state.
    prop = await PropertyService(db=db_session).get(prop_id)
    assert prop.relevance_score == pytest.approx(result.relevance_score)
    assert prop.scored_at is not None
    assert prop.score_reason_json is not None
    assert "sub_scores" in prop.score_reason_json
    assert "weights" in prop.score_reason_json


async def test_fallback_source_flagged(db_session: AsyncSession) -> None:
    prop_id = await _make_property(db_session)
    llm = FakeLLMClient(source="fallback")
    service = _make_service(db_session, llm)

    result = await service.score_property(prop_id)
    assert result.llm_sub_scores_used_fallback is True


async def test_type_fit_prefers_heritage(db_session: AsyncSession) -> None:
    heritage_id = await _make_property(
        db_session, name="Heritage Bungalow", property_type="heritage_home"
    )
    office_id = await _make_property(
        db_session, name="Office Park", property_type="office_space"
    )
    service = _make_service(db_session, FakeLLMClient(shoot_fit=0.5, visual=0.5))

    heritage = await service.score_property(heritage_id)
    office = await service.score_property(office_id)

    heritage_tf = next(s for s in heritage.sub_scores if s.name == "type_fit")
    office_tf = next(s for s in office.sub_scores if s.name == "type_fit")
    assert heritage_tf.value > office_tf.value


async def test_location_demand_prefers_mumbai(db_session: AsyncSession) -> None:
    mumbai_id = await _make_property(db_session, name="M", city="Mumbai")
    unknown_id = await _make_property(db_session, name="U", city="Chotapur")
    service = _make_service(db_session, FakeLLMClient())

    m = await service.score_property(mumbai_id)
    u = await service.score_property(unknown_id)

    m_ld = next(s for s in m.sub_scores if s.name == "location_demand")
    u_ld = next(s for s in u.sub_scores if s.name == "location_demand")
    assert m_ld.value > u_ld.value


async def test_website_quality_rewards_feature_tags(db_session: AsyncSession) -> None:
    basic_id = await _make_property(db_session, name="Basic Villa", website="https://x.com")
    event_id = await _make_property(
        db_session,
        name="Event Villa",
        website="https://y.com",
        feature_tags=["events", "luxury"],
    )
    service = _make_service(db_session, FakeLLMClient())

    basic = await service.score_property(basic_id)
    event = await service.score_property(event_id)

    basic_wq = next(s for s in basic.sub_scores if s.name == "website_quality")
    event_wq = next(s for s in event.sub_scores if s.name == "website_quality")
    assert event_wq.value > basic_wq.value


async def test_no_website_gets_zero_website_quality(db_session: AsyncSession) -> None:
    prop_id = await _make_property(db_session, name="No Web", website=None)
    service = _make_service(db_session, FakeLLMClient())

    result = await service.score_property(prop_id)
    wq = next(s for s in result.sub_scores if s.name == "website_quality")
    assert wq.value == 0.0


async def test_activity_recency_scales_with_reviews(db_session: AsyncSession) -> None:
    zero_id = await _make_property(db_session, name="Z", reviews=0)
    busy_id = await _make_property(db_session, name="B", reviews=250)
    service = _make_service(db_session, FakeLLMClient())

    z = await service.score_property(zero_id)
    b = await service.score_property(busy_id)

    z_r = next(s for s in z.sub_scores if s.name == "activity_recency")
    b_r = next(s for s in b.sub_scores if s.name == "activity_recency")
    assert b_r.value > z_r.value


async def test_ease_of_outreach_prefers_whatsapp(db_session: AsyncSession) -> None:
    prop_id = await _make_property(db_session)
    property_service = PropertyService(db=db_session)
    contact_service = ContactService(db=db_session, property_service=property_service)

    await contact_service.resolve_contacts(
        prop_id,
        [],
        [
            ExtractedContact(
                contact_type="whatsapp",
                value="https://wa.me/919876543210",
                source_url="https://sunset.com",
                extraction_method="whatsapp_link",
                confidence=0.80,
            )
        ],
    )

    service = ScoringService(
        db=db_session,
        llm_client=FakeLLMClient(),  # type: ignore[arg-type]
        property_service=property_service,
        contact_service=contact_service,
    )
    result = await service.score_property(prop_id)

    ease = next(s for s in result.sub_scores if s.name == "ease_of_outreach")
    assert ease.value == 0.9


async def test_score_batch_only_unscored(db_session: AsyncSession) -> None:
    a_id = await _make_property(db_session, name="A")
    await _make_property(db_session, name="B")

    service = _make_service(db_session, FakeLLMClient())

    # Score one first.
    await service.score_property(a_id)

    batch_result = await service.score_batch(only_unscored=True)
    # Only B should have been scored this time.
    assert batch_result.scored == 1
    assert batch_result.failed == 0


async def test_score_batch_counts_fallbacks(db_session: AsyncSession) -> None:
    await _make_property(db_session, name="A")
    await _make_property(db_session, name="B")

    llm = FakeLLMClient(source="fallback")
    service = _make_service(db_session, llm)

    result = await service.score_batch(only_unscored=True)
    assert result.scored == 2
    assert result.llm_fallbacks_used == 2


async def test_score_clamped_to_0_1(db_session: AsyncSession) -> None:
    prop_id = await _make_property(db_session)
    # LLM returns out-of-bounds — service must clamp.
    llm = FakeLLMClient(shoot_fit=1.5, visual=-0.2)
    service = _make_service(db_session, llm)

    result = await service.score_property(prop_id)
    sf = next(s for s in result.sub_scores if s.name == "shoot_fit")
    vu = next(s for s in result.sub_scores if s.name == "visual_uniqueness")
    assert 0.0 <= sf.value <= 1.0
    assert 0.0 <= vu.value <= 1.0
    assert 0.0 <= result.relevance_score <= 1.0

"""Unit tests for QueryBankService (M2)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.schemas.query_bank import QueryBankCreate, QueryBankUpdate
from app.services.query_bank_service import QueryBankService

pytestmark = pytest.mark.asyncio


def _villa_query(city: str = "Alibaug", text: str = "villa in Alibaug") -> QueryBankCreate:
    return QueryBankCreate(
        query_text=text,
        city=city,
        property_type="villa",
        segment_tags=["premium", "outdoor"],
    )


async def test_create_and_list_queries(db_session: AsyncSession) -> None:
    service = QueryBankService(db=db_session)

    created = await service.create_query(_villa_query())

    assert created.query_text == "villa in Alibaug"
    assert created.total_runs == 0
    assert created.quality_score is None

    all_queries = await service.list_queries()
    assert len(all_queries) == 1


async def test_create_duplicate_query_raises_conflict(
    db_session: AsyncSession,
) -> None:
    service = QueryBankService(db=db_session)
    await service.create_query(_villa_query())

    with pytest.raises(ConflictError):
        await service.create_query(_villa_query())


async def test_same_text_different_city_allowed(db_session: AsyncSession) -> None:
    """UNIQUE(query_text, city) — same text in different cities is fine."""
    service = QueryBankService(db=db_session)
    await service.create_query(_villa_query(city="Alibaug", text="heritage villa"))
    await service.create_query(_villa_query(city="Lonavala", text="heritage villa"))

    queries = await service.list_queries()
    assert len(queries) == 2


async def test_list_queries_filters_by_city(db_session: AsyncSession) -> None:
    service = QueryBankService(db=db_session)
    await service.create_query(_villa_query(city="Alibaug", text="villa in Alibaug"))
    await service.create_query(_villa_query(city="Pune", text="villa in Pune"))

    alibaug = await service.list_queries(city="Alibaug")
    assert len(alibaug) == 1
    assert alibaug[0].city == "Alibaug"


async def test_list_queries_filters_by_enabled(db_session: AsyncSession) -> None:
    service = QueryBankService(db=db_session)
    q1 = await service.create_query(_villa_query(text="q1"))
    await service.create_query(_villa_query(text="q2"))
    await service.update_query(q1.id, QueryBankUpdate(is_enabled=False))

    enabled = await service.list_queries(is_enabled=True)
    disabled = await service.list_queries(is_enabled=False)
    assert len(enabled) == 1
    assert len(disabled) == 1


async def test_get_queries_for_discovery_returns_enabled_only(
    db_session: AsyncSession,
) -> None:
    service = QueryBankService(db=db_session)
    q1 = await service.create_query(_villa_query(text="q1"))
    q2 = await service.create_query(_villa_query(text="q2"))
    await service.update_query(q2.id, QueryBankUpdate(is_enabled=False))

    discovery = await service.get_queries_for_discovery()
    discovery_ids = {q.id for q in discovery}
    assert q1.id in discovery_ids
    assert q2.id not in discovery_ids


async def test_get_queries_for_discovery_filters_by_city(
    db_session: AsyncSession,
) -> None:
    service = QueryBankService(db=db_session)
    await service.create_query(_villa_query(city="Alibaug", text="villa in Alibaug"))
    await service.create_query(_villa_query(city="Pune", text="villa in Pune"))

    alibaug_only = await service.get_queries_for_discovery(cities=["Alibaug"])
    assert len(alibaug_only) == 1
    assert alibaug_only[0].city == "Alibaug"


async def test_record_run_result_updates_counters_and_quality(
    db_session: AsyncSession,
) -> None:
    service = QueryBankService(db=db_session)
    created = await service.create_query(_villa_query())

    updated = await service.record_run_result(
        query_id=created.id, results_count=10, new_properties_count=3
    )

    assert updated.total_runs == 1
    assert updated.total_results == 10
    assert updated.new_properties == 3
    assert updated.quality_score == pytest.approx(0.3)


async def test_record_run_result_accumulates(db_session: AsyncSession) -> None:
    service = QueryBankService(db=db_session)
    created = await service.create_query(_villa_query())

    await service.record_run_result(
        query_id=created.id, results_count=10, new_properties_count=5
    )
    final = await service.record_run_result(
        query_id=created.id, results_count=10, new_properties_count=1
    )

    assert final.total_runs == 2
    assert final.total_results == 20
    assert final.new_properties == 6
    assert final.quality_score == pytest.approx(0.3)


async def test_record_run_with_zero_results_leaves_quality_none(
    db_session: AsyncSession,
) -> None:
    service = QueryBankService(db=db_session)
    created = await service.create_query(_villa_query())

    updated = await service.record_run_result(
        query_id=created.id, results_count=0, new_properties_count=0
    )

    assert updated.total_runs == 1
    assert updated.quality_score is None


async def test_delete_query(db_session: AsyncSession) -> None:
    service = QueryBankService(db=db_session)
    created = await service.create_query(_villa_query())

    await service.delete_query(created.id)

    with pytest.raises(NotFoundError):
        await service.get_query(created.id)


async def test_update_to_duplicate_raises_conflict(
    db_session: AsyncSession,
) -> None:
    service = QueryBankService(db=db_session)
    await service.create_query(_villa_query(city="Alibaug", text="q1"))
    q2 = await service.create_query(_villa_query(city="Alibaug", text="q2"))

    with pytest.raises(ConflictError):
        await service.update_query(q2.id, QueryBankUpdate(query_text="q1"))


async def test_get_missing_query_raises_not_found(db_session: AsyncSession) -> None:
    service = QueryBankService(db=db_session)

    with pytest.raises(NotFoundError):
        await service.get_query(uuid.uuid4())

"""Unit tests for SourceService (M1)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.schemas.source import SourceCreate, SourceUpdate
from app.services.source_service import SourceService

pytestmark = pytest.mark.asyncio


def _google_places_source() -> SourceCreate:
    return SourceCreate(
        source_name="google_places",
        source_type="api",
        access_policy="allowed",
        crawl_method="api_call",
        base_url="https://places.googleapis.com",
        rate_limit_rpm=60,
    )


def _airbnb_source() -> SourceCreate:
    return SourceCreate(
        source_name="airbnb",
        source_type="website",
        access_policy="restricted",
        crawl_method="browser_render",
    )


async def test_create_and_get_source(db_session: AsyncSession) -> None:
    service = SourceService(db=db_session)

    created = await service.create_source(_google_places_source())

    assert created.source_name == "google_places"
    assert created.is_enabled is True

    fetched = await service.get_source(created.id)
    assert fetched.id == created.id


async def test_create_duplicate_source_raises_conflict(
    db_session: AsyncSession,
) -> None:
    service = SourceService(db=db_session)
    await service.create_source(_google_places_source())

    with pytest.raises(ConflictError):
        await service.create_source(_google_places_source())


async def test_get_missing_source_raises_not_found(
    db_session: AsyncSession,
) -> None:
    service = SourceService(db=db_session)

    with pytest.raises(NotFoundError):
        await service.get_source(uuid.uuid4())

    with pytest.raises(NotFoundError):
        await service.get_source_by_name("does_not_exist")


async def test_list_sources_filters(db_session: AsyncSession) -> None:
    service = SourceService(db=db_session)
    await service.create_source(_google_places_source())
    await service.create_source(_airbnb_source())

    all_sources = await service.list_sources()
    assert len(all_sources) == 2

    api_only = await service.list_sources(source_type="api")
    assert len(api_only) == 1
    assert api_only[0].source_name == "google_places"


async def test_update_source_fields(db_session: AsyncSession) -> None:
    service = SourceService(db=db_session)
    created = await service.create_source(_google_places_source())

    updated = await service.update_source(
        created.id,
        SourceUpdate(is_enabled=False, rate_limit_rpm=30),
    )

    assert updated.is_enabled is False
    assert updated.rate_limit_rpm == 30
    # Other fields preserved
    assert updated.source_name == "google_places"


async def test_is_source_allowed_policy_gate(db_session: AsyncSession) -> None:
    """Restricted sources must not be allowed for automation even when enabled."""
    service = SourceService(db=db_session)
    await service.create_source(_google_places_source())
    await service.create_source(_airbnb_source())

    assert await service.is_source_allowed("google_places") is True
    assert await service.is_source_allowed("airbnb") is False
    assert await service.is_source_allowed("nonexistent") is False


async def test_is_source_allowed_respects_disabled(db_session: AsyncSession) -> None:
    service = SourceService(db=db_session)
    created = await service.create_source(_google_places_source())

    assert await service.is_source_allowed("google_places") is True

    await service.update_source(created.id, SourceUpdate(is_enabled=False))
    assert await service.is_source_allowed("google_places") is False


async def test_get_crawl_config_returns_source_config(
    db_session: AsyncSession,
) -> None:
    service = SourceService(db=db_session)
    await service.create_source(_google_places_source())

    config = await service.get_crawl_config("google_places")

    assert config.crawl_method == "api_call"
    assert config.rate_limit_rpm == 60
    assert config.base_url == "https://places.googleapis.com"

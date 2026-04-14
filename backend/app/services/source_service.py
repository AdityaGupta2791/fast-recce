"""SourceService — business logic for the Source Registry (M1).

Reads and writes the `sources` table. Other pipeline services consult it to
decide whether a source is allowed for automated crawling and how to crawl it.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.source import Source
from app.schemas.source import SourceCreate, SourceUpdate


@dataclass(frozen=True)
class CrawlConfig:
    """Subset of source config needed by the crawler."""

    crawl_method: str
    rate_limit_rpm: int
    parser_version: str
    base_url: str | None


class SourceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_sources(
        self,
        source_type: str | None = None,
        is_enabled: bool | None = None,
    ) -> list[Source]:
        stmt = select(Source).order_by(Source.source_name)
        if source_type is not None:
            stmt = stmt.where(Source.source_type == source_type)
        if is_enabled is not None:
            stmt = stmt.where(Source.is_enabled.is_(is_enabled))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_source(self, source_id: UUID) -> Source:
        source = await self.db.get(Source, source_id)
        if source is None:
            raise NotFoundError(f"Source {source_id} not found")
        return source

    async def get_source_by_name(self, source_name: str) -> Source:
        stmt = select(Source).where(Source.source_name == source_name)
        result = await self.db.execute(stmt)
        source = result.scalar_one_or_none()
        if source is None:
            raise NotFoundError(f"Source '{source_name}' not found")
        return source

    async def create_source(self, data: SourceCreate) -> Source:
        source = Source(**data.model_dump())
        self.db.add(source)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictError(
                f"Source '{data.source_name}' already exists"
            ) from exc
        await self.db.refresh(source)
        return source

    async def update_source(
        self, source_id: UUID, data: SourceUpdate
    ) -> Source:
        source = await self.get_source(source_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(source, field, value)
        await self.db.flush()
        await self.db.refresh(source)
        return source

    async def is_source_allowed(self, source_name: str) -> bool:
        """Pipeline gate: can we automatically crawl this source?

        A source is only allowed for automation if it is enabled AND has
        access_policy='allowed'. Restricted sources (e.g. Airbnb) return False
        even if enabled — they must be processed via manual analyst input.
        """
        try:
            source = await self.get_source_by_name(source_name)
        except NotFoundError:
            return False
        return source.is_enabled and source.access_policy == "allowed"

    async def get_crawl_config(self, source_name: str) -> CrawlConfig:
        source = await self.get_source_by_name(source_name)
        return CrawlConfig(
            crawl_method=source.crawl_method,
            rate_limit_rpm=source.rate_limit_rpm,
            parser_version=source.parser_version,
            base_url=source.base_url,
        )

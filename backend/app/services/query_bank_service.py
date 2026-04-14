"""QueryBankService — manage discovery queries and track per-query yield (M2)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.exceptions import ConflictError, NotFoundError
from app.models.query_bank import QueryBank
from app.schemas.query_bank import QueryBankCreate, QueryBankUpdate


class QueryBankService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_queries(
        self,
        city: str | None = None,
        property_type: str | None = None,
        is_enabled: bool | None = None,
        sort_by: str = "quality_score_desc",
    ) -> list[QueryBank]:
        stmt = select(QueryBank)
        if city is not None:
            stmt = stmt.where(QueryBank.city == city)
        if property_type is not None:
            stmt = stmt.where(QueryBank.property_type == property_type)
        if is_enabled is not None:
            stmt = stmt.where(QueryBank.is_enabled.is_(is_enabled))

        stmt = self._apply_sort(stmt, sort_by)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_query(self, query_id: UUID) -> QueryBank:
        query = await self.db.get(QueryBank, query_id)
        if query is None:
            raise NotFoundError(f"Query {query_id} not found")
        return query

    async def get_queries_for_discovery(
        self,
        cities: list[str] | None = None,
        property_types: list[str] | None = None,
    ) -> list[QueryBank]:
        """Return enabled queries the pipeline should execute in a run."""
        stmt = select(QueryBank).where(QueryBank.is_enabled.is_(True))
        if cities:
            stmt = stmt.where(QueryBank.city.in_(cities))
        if property_types:
            stmt = stmt.where(QueryBank.property_type.in_(property_types))
        stmt = stmt.order_by(QueryBank.city, QueryBank.property_type)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create_query(self, data: QueryBankCreate) -> QueryBank:
        query = QueryBank(**data.model_dump())
        self.db.add(query)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictError(
                f"Query '{data.query_text}' already exists for city '{data.city}'"
            ) from exc
        await self.db.refresh(query)
        return query

    async def update_query(
        self, query_id: UUID, data: QueryBankUpdate
    ) -> QueryBank:
        query = await self.get_query(query_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(query, field, value)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictError(
                "Updated (query_text, city) collides with an existing query"
            ) from exc
        await self.db.refresh(query)
        return query

    async def delete_query(self, query_id: UUID) -> None:
        query = await self.get_query(query_id)
        await self.db.delete(query)
        await self.db.flush()

    async def record_run_result(
        self,
        query_id: UUID,
        results_count: int,
        new_properties_count: int,
    ) -> QueryBank:
        """Update yield counters after a discovery run executes this query.

        quality_score is recomputed as new_properties / total_results — a
        rolling ratio over the query's lifetime. Queries consistently yielding
        zero new properties decay toward a low score and can be pruned.
        """
        query = await self.get_query(query_id)
        query.total_runs += 1
        query.total_results += results_count
        query.new_properties += new_properties_count
        query.last_run_at = func.now()  # type: ignore[assignment]
        query.quality_score = (
            query.new_properties / query.total_results
            if query.total_results > 0
            else None
        )
        await self.db.flush()
        await self.db.refresh(query)
        return query

    @staticmethod
    def _apply_sort(stmt, sort_by: str):  # type: ignore[no-untyped-def]
        match sort_by:
            case "quality_score_desc":
                return stmt.order_by(
                    QueryBank.quality_score.desc().nulls_last(),
                    QueryBank.created_at.desc(),
                )
            case "quality_score_asc":
                return stmt.order_by(
                    QueryBank.quality_score.asc().nulls_first(),
                    QueryBank.created_at.desc(),
                )
            case "created_at_desc":
                return stmt.order_by(QueryBank.created_at.desc())
            case "new_properties_desc":
                return stmt.order_by(QueryBank.new_properties.desc())
            case _:
                return stmt.order_by(QueryBank.created_at.desc())

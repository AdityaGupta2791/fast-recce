"""AnalyticsService — aggregate stats for the dashboard home (M9)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outreach import OutreachQueue
from app.models.property import Property
from app.schemas.analytics import (
    AnalyticsDashboard,
    OutreachFunnelStats,
    PropertyStats,
)


class AnalyticsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def dashboard(self) -> AnalyticsDashboard:
        property_stats = await self._property_stats()
        outreach_stats = await self._outreach_stats()
        llm_stats = await self._llm_stats()
        return AnalyticsDashboard(
            properties=property_stats,
            outreach=outreach_stats,
            llm=llm_stats,
        )

    async def _property_stats(self) -> PropertyStats:
        total_stmt = select(func.count(Property.id)).where(
            Property.is_duplicate.is_(False)
        )
        total = int((await self.db.execute(total_stmt)).scalar_one())

        status_rows = await self.db.execute(
            select(Property.status, func.count(Property.id))
            .where(Property.is_duplicate.is_(False))
            .group_by(Property.status)
        )
        by_status = {row[0]: int(row[1]) for row in status_rows.all()}

        city_rows = await self.db.execute(
            select(Property.city, func.count(Property.id))
            .where(Property.is_duplicate.is_(False))
            .group_by(Property.city)
            .order_by(func.count(Property.id).desc())
            .limit(10)
        )
        by_city = {row[0]: int(row[1]) for row in city_rows.all()}

        type_rows = await self.db.execute(
            select(Property.property_type, func.count(Property.id))
            .where(Property.is_duplicate.is_(False))
            .group_by(Property.property_type)
            .order_by(func.count(Property.id).desc())
        )
        by_type = {row[0]: int(row[1]) for row in type_rows.all()}

        return PropertyStats(
            total=total, by_status=by_status, by_city=by_city, by_type=by_type
        )

    async def _outreach_stats(self) -> OutreachFunnelStats:
        rows = await self.db.execute(
            select(OutreachQueue.status, func.count(OutreachQueue.id)).group_by(
                OutreachQueue.status
            )
        )
        by_status = {row[0]: int(row[1]) for row in rows.all()}

        pending = by_status.get("pending", 0)
        converted = by_status.get("converted", 0)
        in_progress = sum(
            by_status.get(s, 0)
            for s in ("contacted", "responded", "follow_up", "no_response")
        )
        return OutreachFunnelStats(
            pending=pending, in_progress=in_progress, converted=converted
        )

    async def _llm_stats(self) -> dict[str, int]:
        scored_stmt = select(func.count(Property.id)).where(
            Property.is_duplicate.is_(False), Property.scored_at.is_not(None)
        )
        briefed_stmt = select(func.count(Property.id)).where(
            Property.is_duplicate.is_(False),
            Property.brief_generated_at.is_not(None),
        )
        scored = int((await self.db.execute(scored_stmt)).scalar_one())
        briefed = int((await self.db.execute(briefed_stmt)).scalar_one())
        return {"scored": scored, "briefed": briefed}

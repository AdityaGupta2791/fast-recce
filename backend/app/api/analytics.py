"""Analytics router — dashboard summary (M9)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_analytics_service, get_current_user
from app.models.user import User
from app.schemas.analytics import AnalyticsDashboard
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/dashboard", response_model=AnalyticsDashboard)
async def dashboard(
    _user: User = Depends(get_current_user),
    service: AnalyticsService = Depends(get_analytics_service),
) -> AnalyticsDashboard:
    return await service.dashboard()

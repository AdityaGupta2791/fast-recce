"""FastAPI dependency providers. Wire services + external clients here."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.exceptions import ForbiddenError, UnauthorizedError
from app.models.user import User
from app.services.analytics_service import AnalyticsService
from app.services.auth_service import TokenClaims, decode_token
from app.services.outreach_service import OutreachService
from app.services.property_service import PropertyService
from app.services.query_bank_service import QueryBankService
from app.services.source_service import SourceService
from app.services.user_service import UserService


# --- Session-backed services ---


async def get_source_service(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[SourceService, None]:
    yield SourceService(db=db)


async def get_query_bank_service(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[QueryBankService, None]:
    yield QueryBankService(db=db)


async def get_user_service(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[UserService, None]:
    yield UserService(db=db)


async def get_property_service(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[PropertyService, None]:
    yield PropertyService(db=db)


async def get_outreach_service(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[OutreachService, None]:
    yield OutreachService(db=db)


async def get_analytics_service(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[AnalyticsService, None]:
    yield AnalyticsService(db=db)


# --- Auth dependencies ---


def _parse_bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UnauthorizedError("missing or malformed Authorization header")
    return authorization[7:].strip()


async def get_current_user(
    authorization: str | None = Header(default=None),
    user_service: UserService = Depends(get_user_service),
    settings: Settings = Depends(get_settings),
) -> User:
    token = _parse_bearer_token(authorization)
    claims: TokenClaims | None = decode_token(token, settings=settings)
    if claims is None or claims.token_type != "access":
        raise UnauthorizedError("invalid or expired access token")
    user = await user_service.get(claims.user_id)
    if not user.is_active:
        raise UnauthorizedError("account disabled")
    return user


def require_role(*allowed_roles: str):  # type: ignore[no-untyped-def]
    """Dependency factory enforcing role-based access control."""

    async def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles and user.role != "admin":
            raise ForbiddenError(
                f"role '{user.role}' is not allowed for this action"
            )
        return user

    return _checker

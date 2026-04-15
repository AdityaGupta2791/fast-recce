"""Auth router — login, refresh, me, user management (M9)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    get_current_user,
    get_user_service,
    require_role,
)
from app.config import Settings, get_settings
from app.exceptions import UnauthorizedError
from app.models.user import User
from app.schemas.auth import (
    AccessTokenResponse,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.auth_service import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.services.user_service import UserService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    user_service: UserService = Depends(get_user_service),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    user = await user_service.authenticate(data.email, data.password)
    access, expires_in = create_access_token(
        user_id=user.id, email=user.email, role=user.role, settings=settings
    )
    refresh = create_refresh_token(
        user_id=user.id, email=user.email, role=user.role, settings=settings
    )
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=expires_in,
        user=UserRead.model_validate(user),
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    data: RefreshRequest,
    user_service: UserService = Depends(get_user_service),
    settings: Settings = Depends(get_settings),
) -> AccessTokenResponse:
    claims = decode_token(data.refresh_token, settings=settings)
    if claims is None or claims.token_type != "refresh":
        raise UnauthorizedError("invalid or expired refresh token")

    user = await user_service.get(claims.user_id)
    if not user.is_active:
        raise UnauthorizedError("account disabled")

    access, expires_in = create_access_token(
        user_id=user.id, email=user.email, role=user.role, settings=settings
    )
    return AccessTokenResponse(access_token=access, expires_in=expires_in)


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(user)


# --- User management (admin only) ---


@router.get("/users", response_model=list[UserRead])
async def list_users(
    _admin: User = Depends(require_role("admin")),
    user_service: UserService = Depends(get_user_service),
) -> list[UserRead]:
    users = await user_service.list_users()
    return [UserRead.model_validate(u) for u in users]


@router.post(
    "/users", response_model=UserRead, status_code=status.HTTP_201_CREATED
)
async def create_user(
    data: UserCreate,
    _admin: User = Depends(require_role("admin")),
    user_service: UserService = Depends(get_user_service),
) -> UserRead:
    user = await user_service.create(data)
    return UserRead.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: UUID,
    data: UserUpdate,
    _admin: User = Depends(require_role("admin")),
    user_service: UserService = Depends(get_user_service),
) -> UserRead:
    user = await user_service.update(user_id, data)
    return UserRead.model_validate(user)

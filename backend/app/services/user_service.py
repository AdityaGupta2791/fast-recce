"""UserService — lookup + CRUD for dashboard users (M9)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError, UnauthorizedError
from app.models.user import User
from app.schemas.auth import UserCreate, UserUpdate
from app.services.auth_service import hash_password, verify_password


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_users(self) -> list[User]:
        stmt = select(User).order_by(User.email)
        return list((await self.db.execute(stmt)).scalars().all())

    async def get(self, user_id: UUID) -> User:
        user = await self.db.get(User, user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        return user

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(func.lower(User.email) == email.lower())
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def create(self, data: UserCreate) -> User:
        if await self.get_by_email(data.email):
            raise ConflictError(f"user with email '{data.email}' already exists")
        user = User(
            email=data.email,
            password_hash=hash_password(data.password),
            full_name=data.full_name,
            role=data.role,
        )
        self.db.add(user)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictError(f"user with email '{data.email}' already exists") from exc
        await self.db.refresh(user)
        return user

    async def update(self, user_id: UUID, data: UserUpdate) -> User:
        user = await self.get(user_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(user, field, value)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def authenticate(self, email: str, password: str) -> User:
        """Verify credentials. Raises UnauthorizedError on any failure mode."""
        user = await self.get_by_email(email)
        if user is None or not user.is_active:
            raise UnauthorizedError("invalid email or password")
        if not verify_password(password, user.password_hash):
            raise UnauthorizedError("invalid email or password")
        return user

"""Pytest fixtures shared across test modules.

Provides an isolated in-memory SQLite database per test via SQLAlchemy async.
Each test gets a fresh schema and a scoped session. No Docker or PostgreSQL
is required to run unit tests.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.models import discovery, query_bank, source  # noqa: F401 — register models

_MODELS_REGISTERED = (source, query_bank, discovery)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Fresh in-memory SQLite DB per test, with schema created from ORM metadata."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()

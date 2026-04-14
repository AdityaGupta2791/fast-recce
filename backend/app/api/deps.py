"""FastAPI dependency providers. Wire services and external clients here."""

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.query_bank_service import QueryBankService
from app.services.source_service import SourceService


async def get_source_service(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[SourceService, None]:
    yield SourceService(db=db)


async def get_query_bank_service(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[QueryBankService, None]:
    yield QueryBankService(db=db)

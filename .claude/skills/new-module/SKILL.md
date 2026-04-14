---
name: new-module
description: Scaffold a new FastRecce backend module following project conventions. Creates SQLAlchemy model, Pydantic schemas, service class, API router, and unit test. Use when the user says "/new-module" or asks to create a new module, new service, or new resource.
---

# /new-module — FastRecce Module Scaffolder

Creates all the files required for a new FastRecce backend module, following the conventions defined in `docs/service-design.md` and `docs/database-schema.md`.

## When to Use

Invoke this skill when the user:
- Says `/new-module <ModuleName>` (e.g. `/new-module sources`)
- Asks to "scaffold a new module"
- Asks to "create a new service" for a specific domain

## Arguments

- **module_name** (required): snake_case name. Examples: `sources`, `query_bank`, `outreach`.

## What It Creates

For a module named `<module>`:

| File | Purpose |
|---|---|
| `backend/app/models/<module>.py` | SQLAlchemy ORM model(s) |
| `backend/app/schemas/<module>.py` | Pydantic request/response schemas |
| `backend/app/services/<module>_service.py` | Business logic service class |
| `backend/app/api/<module>.py` | FastAPI router with endpoints |
| `backend/tests/unit/test_<module>_service.py` | Unit tests |

Also:
- Registers the model import in `backend/alembic/env.py`
- Mounts the router in `backend/app/api/main.py` (under `/api/v1/<module>`)

## Conventions to Follow

1. **Model class name:** PascalCase singular (e.g. `Source`, `QueryBank`, `Property`).
2. **Table name:** snake_case plural (e.g. `sources`, `query_bank`, `properties`).
3. **Service class name:** `<Module>Service` (e.g. `SourceService`, `QueryBankService`).
4. **Primary key:** Always `id: UUID` with `default=uuid.uuid4`.
5. **Timestamps:** Every table has `created_at` and `updated_at` as `timestamptz` with `DEFAULT now()`.
6. **Async everywhere:** Services use `AsyncSession`. API routes are `async def`.
7. **Dependency injection:** Services take `db: AsyncSession` in `__init__`. Wire up via `api/deps.py`.
8. **No business logic in routes:** Routes validate input → call service → return response.
9. **Schemas:** Separate `<Module>Create`, `<Module>Update`, `<Module>Read` Pydantic models.

## Process

1. Read `docs/database-schema.md` to find the correct schema for the requested module.
2. Read `docs/service-design.md` to find the service interface definition.
3. Read `docs/api-spec.md` for the endpoint contracts.
4. Create all 5 files following the templates below.
5. Update `backend/alembic/env.py` to import the new model.
6. Update `backend/app/api/main.py` to register the new router.
7. Report to the user: files created + next steps (run migration).

## File Templates

### Model (`models/<module>.py`)

```python
"""<Module> ORM model. Maps to the <table_name> table."""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Boolean, CheckConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class <Module>(Base):
    __tablename__ = "<table_name>"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # ... columns from docs/database-schema.md
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

### Service (`services/<module>_service.py`)

```python
"""<Module>Service — business logic for <module> module (M<N>)."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.<module> import <Module>
from app.schemas.<module> import <Module>Create, <Module>Update


class <Module>Service:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self) -> list[<Module>]:
        result = await self.db.execute(select(<Module>))
        return list(result.scalars().all())

    async def get(self, item_id: UUID) -> <Module>:
        item = await self.db.get(<Module>, item_id)
        if item is None:
            raise NotFoundError(f"<Module> {item_id} not found")
        return item

    async def create(self, data: <Module>Create) -> <Module>:
        item = <Module>(**data.model_dump())
        self.db.add(item)
        await self.db.flush()
        return item

    async def update(self, item_id: UUID, data: <Module>Update) -> <Module>:
        item = await self.get(item_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(item, field, value)
        await self.db.flush()
        return item
```

### Schema (`schemas/<module>.py`)

```python
"""<Module> Pydantic schemas for API request/response bodies."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class <Module>Base(BaseModel):
    # Common fields
    ...


class <Module>Create(<Module>Base):
    pass


class <Module>Update(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # All fields optional
    ...


class <Module>Read(<Module>Base):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    updated_at: datetime
```

### Router (`api/<module>.py`)

```python
"""<Module> API router. Mounted at /api/v1/<module>."""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_<module>_service
from app.schemas.<module> import <Module>Create, <Module>Update, <Module>Read
from app.services.<module>_service import <Module>Service

router = APIRouter(prefix="/api/v1/<module>", tags=["<module>"])


@router.get("", response_model=list[<Module>Read])
async def list_items(service: <Module>Service = Depends(get_<module>_service)):
    return await service.list()


@router.get("/{item_id}", response_model=<Module>Read)
async def get_item(item_id: UUID, service: <Module>Service = Depends(get_<module>_service)):
    return await service.get(item_id)


@router.post("", response_model=<Module>Read, status_code=201)
async def create_item(data: <Module>Create, service: <Module>Service = Depends(get_<module>_service)):
    return await service.create(data)


@router.patch("/{item_id}", response_model=<Module>Read)
async def update_item(item_id: UUID, data: <Module>Update, service: <Module>Service = Depends(get_<module>_service)):
    return await service.update(item_id, data)
```

### Unit Test (`tests/unit/test_<module>_service.py`)

```python
"""Unit tests for <Module>Service."""

import pytest

# Tests will be filled in as service methods are implemented
```

## After Scaffolding

Remind the user:
1. Add the new model import to `backend/alembic/env.py`.
2. Run the `/add-migration` skill to generate a migration for the new table.
3. Run `alembic upgrade head` to apply the migration.

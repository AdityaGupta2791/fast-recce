---
name: new-module
description: Scaffold a new FastRecce backend module following project conventions. Supports both CRUD modules (user-facing REST resources) and pipeline-service modules (internal batch services, no REST). Use when the user says "/new-module" or asks to create a new module, new service, or new resource.
---

# /new-module — FastRecce Module Scaffolder

Creates the files for a new FastRecce backend module, following the conventions in `docs/module-breakdown.md`, `docs/database-schema.md`, `docs/service-design.md`, and `docs/api-spec.md`.

## When to Use

Invoke this skill when the user:
- Says `/new-module <module_name>` (e.g. `/new-module sources`, `/new-module discovery`)
- Asks to scaffold a new backend module or service
- Starts implementation of a module defined in `docs/module-breakdown.md`

## Arguments

- **module_name** (required): snake_case. Examples: `sources`, `query_bank`, `discovery`, `contacts`.

---

## Step 0 — Classify the Module

**Before writing any files**, decide which template to use by reading `docs/module-breakdown.md` and `docs/api-spec.md` for the module:

| Type | Decision Signal | Examples in FastRecce |
|---|---|---|
| **CRUD** | Has user-facing endpoints in `docs/api-spec.md` | M1 Sources, M2 Query Bank, M9 Outreach |
| **Pipeline-service** | No REST endpoints in `docs/api-spec.md` — triggered via the pipeline orchestrator | M3 Discovery, M4 Crawler, M5 Contacts, M6 Dedup, M7 Scoring, M8 Briefs |

**Tell the user which type you detected** before scaffolding. If ambiguous, ask.

Key differences in what gets created:

|  | CRUD | Pipeline-service |
|---|---|---|
| Model file | ✅ yes | ✅ yes |
| Schema file | ✅ yes (Create/Update/Read) | ✅ yes (domain types like `RunRequest`, `RunResult`) |
| Service file | ✅ yes (list/get/create/update) | ✅ yes (domain-specific methods per `service-design.md`) |
| API router | ✅ yes | ❌ skip (not exposed) |
| `api/deps.py` wiring | ✅ yes | Only if service is consumed by another REST endpoint |
| `api/main.py` router mount | ✅ yes | ❌ skip |
| Integration clients (`app/integrations/`) | ❌ typically not | ✅ often yes (e.g. Google Places, LLM, S3) |
| Unit tests | ✅ yes | ✅ yes (mock external clients) |

---

## Step 1 — Read the Relevant Docs

- `docs/module-breakdown.md` — owner, data entities, dependencies
- `docs/database-schema.md` — exact column definitions, indexes, constraints for this module's tables
- `docs/service-design.md` — the service class interface (method signatures)
- `docs/api-spec.md` — endpoint contracts (CRUD modules only)

Use the actual schemas from these docs. **Do not invent columns.**

---

## Step 2 — Create the Files

### Naming Conventions (both types)

- **Model class:** PascalCase singular (e.g. `Source`, `QueryBank`, `DiscoveryCandidate`)
- **Table name:** snake_case (plural for CRUD, singular for event/staging tables — match the schema doc)
- **Service class:** `<Module>Service` (e.g. `SourceService`, `DiscoveryService`)
- **File names:** `models/<module>.py`, `schemas/<module>.py`, `services/<module>_service.py`, `api/<module>.py`, `tests/unit/test_<module>_service.py`

### Model Conventions (both types)

```python
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Boolean, CheckConstraint, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy import JSON  # for cross-dialect JSONB fallback
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import <ENUM_CONSTANT>, check_constraint

# Use this helper for any JSONB column so unit tests on SQLite work:
_JSONType = JSONB().with_variant(JSON(), "sqlite")


class <Module>(Base):
    __tablename__ = "<table_name>"
    __table_args__ = (
        CheckConstraint(
            f"<col> {check_constraint(<ENUM_TUPLE>)}",
            name="ck_<table>_<col>",
        ),
        Index("idx_<table>_<col>", "<col>", postgresql_where="..."),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # ... domain columns matching docs/database-schema.md
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

**Rules:**
- Add string enum values to `app/models/enums.py` first, then reference from models
- Always use `_JSONType` (not bare `JSONB`) for JSONB columns so tests run on SQLite
- All timestamps are `DateTime(timezone=True)`
- UUIDs with `default=uuid.uuid4` (client-side). For `bulk_insert` in seed migrations, generate UUIDs explicitly.

---

### Schema File Conventions

**CRUD modules:**

```python
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

<EnumType> = Literal["value_a", "value_b"]  # mirror the CHECK constraint


class <Module>Base(BaseModel):
    # Common fields with validation (min_length, ge/le, etc.)
    ...


class <Module>Create(<Module>Base):
    pass


class <Module>Update(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # All fields Optional; only set fields are applied
    ...


class <Module>Read(<Module>Base):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    updated_at: datetime
```

**Pipeline-service modules:**

```python
class <Module>Base(BaseModel): ...
class <Module>Create(<Module>Base): pass
class <Module>Read(<Module>Base):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    # pipeline state fields (status, error_message, processed_at, etc.)


class <Module>RunRequest(BaseModel):
    """Input for triggering a pipeline run (optional filters)."""
    ...


class <Module>RunResult(BaseModel):
    """Summary returned by the service's run method."""
    items_processed: int
    items_created: int
    errors: list[str] = Field(default_factory=list)
    duration_seconds: float
```

---

### Service File Conventions

**All services:**
- `__init__` takes `db: AsyncSession` and any dependencies (other services, integration clients)
- Domain exceptions from `app.exceptions` (`NotFoundError`, `ConflictError`, etc.)
- Use `await self.db.flush()` after mutations (commit is handled by the FastAPI dependency / pipeline runner)
- Wrap bulk-insert/upsert conflicts in `try/except IntegrityError` for cross-dialect tests

**CRUD service template:**

```python
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.<module> import <Module>
from app.schemas.<module> import <Module>Create, <Module>Update


class <Module>Service:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_items(self, **filters) -> list[<Module>]:
        stmt = select(<Module>)
        # apply filters
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_item(self, item_id: UUID) -> <Module>:
        item = await self.db.get(<Module>, item_id)
        if item is None:
            raise NotFoundError(f"<Module> {item_id} not found")
        return item

    async def create_item(self, data: <Module>Create) -> <Module>:
        item = <Module>(**data.model_dump())
        self.db.add(item)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictError("...") from exc
        await self.db.refresh(item)
        return item

    async def update_item(self, item_id: UUID, data: <Module>Update) -> <Module>:
        item = await self.get_item(item_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(item, field, value)
        await self.db.flush()
        await self.db.refresh(item)
        return item
```

**Pipeline-service template:**

Do NOT use the CRUD template. Write methods matching `docs/service-design.md` for that module. Typical shape:

```python
class <Module>Service:
    def __init__(
        self,
        db: AsyncSession,
        <external_client>: <Client>,
        <other_service>: <OtherService>,
    ) -> None:
        self.db = db
        self.<client> = <external_client>
        self.<other> = <other_service>

    async def run(
        self, filters: <Module>RunRequest
    ) -> <Module>RunResult:
        """Main entry point — called by the pipeline orchestrator."""
        # Isolate per-item failures: each item in a try/except so one bad
        # record doesn't kill the whole run. Collect errors in the result.

    async def list_recent(self, status: str | None = None, limit: int = 50): ...
    async def mark_processed(self, item_id: UUID): ...
    async def mark_failed(self, item_id: UUID, error: str): ...
```

---

### Router File (CRUD only — SKIP for pipeline-services)

```python
from uuid import UUID
from fastapi import APIRouter, Depends, status

from app.api.deps import get_<module>_service
from app.schemas.<module> import <Module>Create, <Module>Update, <Module>Read
from app.services.<module>_service import <Module>Service

router = APIRouter(prefix="/api/v1/<module>", tags=["<module>"])


@router.get("", response_model=list[<Module>Read])
async def list_items(service: <Module>Service = Depends(get_<module>_service)):
    items = await service.list_items()
    return [<Module>Read.model_validate(i) for i in items]

# ... get, post, patch, delete as needed per docs/api-spec.md
```

---

### Unit Test File

**CRUD modules** — test CRUD operations, filters, conflict/not-found paths:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.schemas.<module> import <Module>Create
from app.services.<module>_service import <Module>Service

pytestmark = pytest.mark.asyncio


async def test_create_and_get(db_session: AsyncSession) -> None:
    service = <Module>Service(db=db_session)
    created = await service.create_item(<Module>Create(...))
    fetched = await service.get_item(created.id)
    assert fetched.id == created.id
```

**Pipeline-service modules** — use a fake integration client (no external I/O):

```python
class Fake<Client>:
    """In-memory stand-in — drives pre-canned responses, records calls."""
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    async def some_method(self, arg):
        self.calls.append(arg)
        return self.responses.get(arg, default)


async def test_run_happy_path(db_session: AsyncSession) -> None:
    fake = Fake<Client>(responses={...})
    service = <Module>Service(db=db_session, client=fake, ...)
    result = await service.run(...)
    assert result.items_created == N
```

---

## Step 3 — Wire Into the Application

Always:
1. **Import the model in `alembic/env.py`** so autogenerate sees it:
   ```python
   from app.models import <existing>, <new>  # noqa: F401,E402
   _MODELS_REGISTERED = (<existing>, <new>)
   ```
2. **Import the model in `tests/conftest.py`** so SQLite test DB creates the table:
   ```python
   from app.models import <existing>, <new>  # noqa: F401
   _MODELS_REGISTERED = (<existing>, <new>)
   ```

**CRUD modules only:**

3. **Add a provider in `app/api/deps.py`**:
   ```python
   async def get_<module>_service(db: AsyncSession = Depends(get_db)):
       yield <Module>Service(db=db)
   ```
4. **Mount the router in `app/api/main.py`** under `_register_routers`:
   ```python
   from app.api import <module>
   app.include_router(<module>.router)
   ```

---

## Step 4 — Run the Tests

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_<module>_service.py -v
```

All tests should pass before moving on.

---

## Step 5 — Generate the Migration

Invoke the `/add-migration` skill:
```
/add-migration add <table_name> table
```

Do NOT run `alembic revision --autogenerate` manually — the `/add-migration` skill validates the output.

---

## Common Pitfalls

| Pitfall | Fix |
|---|---|
| JSONB column fails on SQLite test | Use `_JSONType = JSONB().with_variant(JSON(), "sqlite")` |
| `bulk_insert` in seed migration fails with NULL ID | Client-side `default=uuid.uuid4` doesn't fire on bulk_insert — generate UUIDs explicitly in seed rows |
| Empty autogenerate output | Forgot to import new model in `alembic/env.py` |
| PG-specific `ON CONFLICT` breaks SQLite tests | Use `try/except IntegrityError` for portability |
| Tests pass but real request fails | Service uses columns not in schema — re-check `docs/database-schema.md` |
| Unused-import linter warnings on model registration | Reference imports explicitly: `_MODELS_REGISTERED = (a, b, c)` |

---

## Report to the User

After scaffolding, report:

1. **Module type classified as:** CRUD or pipeline-service
2. **Files created:** list the full paths
3. **Files modified:** `alembic/env.py`, `tests/conftest.py`, `api/deps.py` (CRUD), `api/main.py` (CRUD)
4. **Next steps:** run tests → run `/add-migration <description>` → apply migration → (optional) live smoke test

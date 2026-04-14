# FastRecce — Location Acquisition OS

AI-assisted location scouting platform. Discovers shoot-worthy properties from compliant sources, enriches them with contact/feature data, scores them for shoot relevance, and feeds a human outreach pipeline.

## Architecture

Modular monolith with two deployable units:

- **Pipeline** (`backend/app/pipeline/`) — scheduled batch worker (daily/weekly/monthly)
- **Dashboard API + SPA** (`backend/app/api/` + `frontend/`) — always-on internal web app

See [`docs/`](./docs/) for complete architecture documentation:

- [Module Breakdown](./docs/module-breakdown.md)
- [System Architecture](./docs/system-architecture.md)
- [Database Schema](./docs/database-schema.md)
- [API Specification](./docs/api-spec.md)
- [Service Layer Design](./docs/service-design.md)
- [Frontend Data Flow](./docs/frontend-design.md)

## Prerequisites

- Python 3.12+
- Node.js 20+
- Docker + Docker Compose
- `uv` (recommended) or `pip` for Python package management

## Quick Start

### 1. Start infrastructure

```bash
docker-compose up -d
```

This starts:
- PostgreSQL 16 with PostGIS (port 5432)
- Redis 7 (port 6379)
- MinIO S3-compatible storage (ports 9000, 9001)

Verify with `docker ps` — three containers should be running.

### 2. Configure environment

```bash
cp backend/.env.example backend/.env
# Edit backend/.env — set JWT_SECRET_KEY, GOOGLE_PLACES_API_KEY, GEMINI_API_KEY
```

Generate a JWT secret:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Install backend dependencies

```bash
cd backend
uv venv
uv pip install -e ".[dev]"
# Or with pip: python -m venv .venv && .venv/bin/activate && pip install -e ".[dev]"
```

### 4. Run database migrations

```bash
cd backend
alembic upgrade head
```

### 5. Install frontend dependencies

```bash
cd frontend
npm install
```

### 6. Run everything

Three terminals:

```bash
# Terminal 1: Dashboard API
cd backend && uvicorn app.api.main:app --reload

# Terminal 2: Frontend SPA
cd frontend && npm run dev

# Terminal 3 (later): Pipeline worker
cd backend && python -m app.pipeline.daily
```

Visit:
- Dashboard: http://localhost:5173
- API docs: http://localhost:8000/api/docs
- MinIO console: http://localhost:9001 (admin/minioadmin)

## Project Structure

```
FastRecce/
├── backend/                # Python backend (pipeline + API)
│   ├── app/
│   │   ├── models/         # SQLAlchemy ORM models
│   │   ├── schemas/        # Pydantic API schemas
│   │   ├── services/       # Business logic (one per module)
│   │   ├── api/            # FastAPI routes
│   │   ├── pipeline/       # Scheduled workers
│   │   └── integrations/   # External clients (Google Places, Gemini, S3)
│   ├── alembic/            # Database migrations
│   └── tests/              # Pytest unit + integration tests
├── frontend/               # React + TypeScript SPA
│   └── src/
│       ├── api/            # API client (axios)
│       ├── components/     # React components
│       ├── pages/          # Route pages
│       └── hooks/          # Custom React hooks
├── docs/                   # Architecture documentation
├── .claude/                # Claude Code hooks + skills
├── docker-compose.yml      # Local dev infrastructure
└── README.md
```

## Development Workflow

This project is built using [Claude Code](https://claude.com/claude-code) with custom skills and hooks:

### Available Skills

- **`/new-module <name>`** — scaffold a new backend module (model + schema + service + API route + tests)
- **`/add-migration <description>`** — generate an Alembic migration from current model changes

### Hooks

- **PostToolUse** — auto-runs `ruff check --fix` on Python files and `tsc --noEmit` on TypeScript files after Claude edits them

## Running Tests

```bash
cd backend
pytest                      # All tests
pytest tests/unit           # Unit tests only
pytest --cov=app            # With coverage
```

## Linting & Type Checking

```bash
# Backend
cd backend
ruff check .                # Lint
ruff format .               # Format
mypy app                    # Type check

# Frontend
cd frontend
npm run lint                # ESLint
npm run typecheck           # tsc
```

## Build Phases

See [`docs/module-breakdown.md`](./docs/module-breakdown.md) for the full build order.

- **Phase 1:** Source Registry (M1), Query Bank (M2), DB setup ← **in progress**
- **Phase 2:** Discovery Engine (M3)
- **Phase 3:** Crawl & Extraction (M4), Contacts (M5), Dedup (M6)
- **Phase 4:** Scoring (M7), AI Briefs (M8)
- **Phase 5:** Dashboard (M9), Pipeline Orchestrator (M10)

## License

Proprietary. Internal use only.

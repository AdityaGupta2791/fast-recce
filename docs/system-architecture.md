# FastRecce Platform — System Architecture

> **Document Version:** 1.0
> **Date:** 2026-04-13
> **Status:** Draft — Pending Confirmation
> **Depends On:** [module-breakdown.md](./module-breakdown.md)

---

## 1. Architecture Style: Modular Monolith (Two Deployable Units)

### Why NOT Microservices

- Team size is small (likely 1-3 engineers for MVP)
- Daily processing volume is low-to-moderate (hundreds to low thousands of properties)
- No independent scaling requirements between modules yet
- Microservices add operational complexity (service mesh, distributed tracing, contract testing) that doesn't pay off at this stage

### Why Two Units Instead of One

The system has two fundamentally different runtime profiles:

| Concern | Pipeline | Dashboard |
|---|---|---|
| **Runtime** | Batch job, scheduled | Always-on web server |
| **Load pattern** | Burst (daily/weekly runs) | Steady (reviewer interactions) |
| **Failure mode** | A crawl can hang for minutes | Must respond in <200ms |
| **Scaling axis** | I/O concurrency (network calls) | Request concurrency |
| **Restart tolerance** | Can restart mid-pipeline (idempotent) | Must stay available |

Coupling them in a single process means a stuck Playwright crawl could starve the dashboard of resources, or a dashboard deployment could interrupt a running pipeline.

### The Two Units

```
┌─────────────────────────────────────────────┐
│              UNIT 1: PIPELINE               │
│                                             │
│  Discovery → Crawl → Contacts → Dedup      │
│  → Scoring → Briefs                        │
│                                             │
│  Scheduled by: Prefect / Cron              │
│  Runtime: Python workers                    │
│  Modules: M1-M8, M10                       │
└──────────────────┬──────────────────────────┘
                   │
                   │  Shared PostgreSQL
                   │  Shared Redis
                   │
┌──────────────────┴──────────────────────────┐
│            UNIT 2: DASHBOARD API            │
│                                             │
│  FastAPI (REST) ← React + Tailwind SPA     │
│                                             │
│  Reads: properties, scores, contacts        │
│  Writes: review decisions, outreach status  │
│  Modules: M9 (+ read access to all)        │
└─────────────────────────────────────────────┘
```

Both units share the same PostgreSQL database and Redis instance. They share the same Python codebase (same repo, same models, same service layer) but run as separate processes.

---

## 2. Tech Stack Decisions

### Backend

| Component | Choice | Reasoning |
|---|---|---|
| **Language** | Python 3.12+ | PRD specifies Python. Strongest ecosystem for web scraping, LLM integration, and data processing. |
| **API Framework** | FastAPI | Async support for I/O-bound crawl work. Auto-generated OpenAPI docs. Pydantic validation. |
| **ORM** | SQLAlchemy 2.0 (async) | Mature, supports complex queries, good PostgreSQL support. Async mode for non-blocking DB calls in the API server. |
| **Migration** | Alembic | Standard for SQLAlchemy. Versioned schema migrations. |
| **HTTP Client** | httpx (async) | Async HTTP for API calls and website fetching. Connection pooling. |
| **HTML Parsing** | BeautifulSoup4 + lxml | Fast, battle-tested. lxml for speed, BS4 for convenience. |
| **Browser Rendering** | Playwright | Only for JS-rendered pages. Not the default — used when `crawl_method = browser_render`. |
| **Task Queue** | Redis + arq (or Celery) | arq is lightweight async Python task queue on Redis. Celery if heavier scheduling needs emerge. |
| **Scheduler** | Prefect 2 | Better observability than raw cron. DAG-based flows, built-in retry, dashboard for pipeline monitoring. Falls back to APScheduler if simpler needs. |
| **LLM Integration** | Google Gemini API (via `google-genai` SDK) | For brief generation and subjective scoring (visual_uniqueness, shoot_fit). Structured outputs via `response_schema`. |

### Database & Storage

| Component | Choice | Reasoning |
|---|---|---|
| **Primary DB** | PostgreSQL 16 | PRD specifies it. JSONB for flexible schema fields (score_reason_json, raw_features_json). PostGIS extension for geo queries (dedup by distance). |
| **Cache / Queue Backend** | Redis 7 | Job queues, dedup caches (place_id seen-set), rate limiting counters. |
| **Object Storage** | S3-compatible (MinIO local / AWS S3 prod) | Raw HTML snapshots, media files. Not in PostgreSQL — keeps the DB lean. |
| **Search (future)** | PostgreSQL full-text search initially → Meilisearch if needed | Property search on the dashboard doesn't need Elasticsearch at MVP scale. |

### Frontend

| Component | Choice | Reasoning |
|---|---|---|
| **Framework** | React 18 + TypeScript | PRD specifies React. TypeScript for type safety on API contracts. |
| **Styling** | Tailwind CSS | PRD specifies it. Utility-first, fast for internal tool UI. |
| **Component Library** | shadcn/ui | Not a dependency — copy-paste components built on Radix + Tailwind. Full control, no version lock-in. |
| **State Management** | TanStack Query (React Query) | Server-state management for API data. Handles caching, refetch, optimistic updates. No Redux needed. |
| **Routing** | React Router v7 | Standard for SPAs. |
| **Build Tool** | Vite | Fast dev server, good production builds. |

### Infrastructure (MVP)

| Component | Choice | Reasoning |
|---|---|---|
| **Hosting** | Single VPS (Railway / Render / DigitalOcean) | MVP doesn't need Kubernetes. One server can run both units + PostgreSQL + Redis. |
| **CI/CD** | GitHub Actions | Standard. Lint → Test → Build → Deploy. |
| **Monitoring** | Sentry (errors) + Prefect UI (pipeline) | Lightweight. No Grafana/Prometheus stack needed at MVP. |
| **Secrets** | Environment variables via hosting platform | No Vault needed at MVP. Migrate to proper secrets manager when team grows. |

---

## 3. High-Level Data Flow

### Daily Pipeline Flow

```
┌─────────┐     ┌──────────┐     ┌──────────┐     ┌───────────┐
│  Query   │────▶│ Google   │────▶│ Candidate│────▶│  Crawl    │
│  Bank    │     │ Places   │     │ Staging  │     │  Website  │
│  (M2)    │     │ API (M3) │     │  Table   │     │  (M4)     │
└─────────┘     └──────────┘     └──────────┘     └─────┬─────┘
                                                        │
                                          ┌─────────────┼─────────────┐
                                          │             │             │
                                          ▼             ▼             ▼
                                   ┌──────────┐  ┌──────────┐  ┌──────────┐
                                   │ Contact  │  │  Dedup   │  │  Media   │
                                   │ Resolve  │  │  Check   │  │ Extract  │
                                   │  (M5)    │  │  (M6)    │  │  (M4)    │
                                   └────┬─────┘  └────┬─────┘  └────┬─────┘
                                        │             │             │
                                        └──────┬──────┘─────────────┘
                                               │
                                               ▼
                                       ┌──────────────┐
                                       │  Canonical   │
                                       │  Property    │
                                       │  Upsert      │
                                       └──────┬───────┘
                                              │
                                    ┌─────────┼─────────┐
                                    │                   │
                                    ▼                   ▼
                             ┌──────────┐        ┌──────────┐
                             │ Scoring  │        │ AI Brief │
                             │  (M7)    │───────▶│  (M8)    │
                             └──────────┘        └──────────┘
                                                      │
                                                      ▼
                                              ┌──────────────┐
                                              │  Dashboard   │
                                              │  Lead Queue  │
                                              │  (M9)        │
                                              └──────────────┘
```

### Pipeline Stage Details

| Stage | Input | Processing | Output | Failure Strategy |
|---|---|---|---|---|
| **1. Discovery** | Query bank queries | Google Places Text Search → Place Details | Candidate records with place_id, name, phone, website, lat/lng | Retry 3x with backoff. Skip query on persistent failure. Log to crawl_runs. |
| **2. Dedup Filter** | Candidate records | Check place_id and phone against existing properties | Filtered list: new candidates only | Pass-through on failure (better to have duplicates than miss properties). |
| **3. Website Crawl** | Candidate website URLs | Fetch home + contact + about pages. Parse HTML. | Raw HTML snapshots + extracted data JSON | Timeout at 30s per page. Playwright fallback for JS sites. Mark as "crawl_failed" and continue. |
| **4. Contact Resolution** | Extracted contacts + API contacts | Merge, validate, apply precedence rules, flag personal contacts | `property_contacts` records | Never fail the pipeline — worst case is no contacts extracted. |
| **5. Canonical Upsert** | All extracted data | Create or update `properties` record. Link `property_sources`. | Canonical property entity | Idempotent upsert on (normalized_name + city + lat/lng). |
| **6. Scoring** | Property features + contacts + location | Apply weighted formula, compute sub-scores | `relevance_score` + `score_reason_json` | Default to 0.5 if scoring fails. Flag for manual review. |
| **7. Brief Generation** | Property data + scores | LLM prompt with property context | `short_brief` text | Use template-based fallback if LLM fails. |

### Dashboard Data Flow

```
┌────────────────────────────────────────────────────────┐
│                    React SPA (M9)                       │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │Lead Queue│  │ Property │  │ Outreach │  │Pipeline│ │
│  │  View    │  │  Detail  │  │ Kanban   │  │ Health │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───┬────┘ │
└───────┼──────────────┼───────────┼──────────────┼──────┘
        │              │           │              │
        ▼              ▼           ▼              ▼
┌────────────────────────────────────────────────────────┐
│                  FastAPI REST API                       │
│                                                         │
│  GET /properties      GET /properties/:id               │
│  GET /properties/:id/contacts                           │
│  PATCH /properties/:id/review                           │
│  GET /outreach        PATCH /outreach/:id               │
│  GET /pipeline/runs   GET /pipeline/health              │
│  GET /queries         POST /queries                     │
│  POST /properties/manual-import                         │
└───────────────────────┬────────────────────────────────┘
                        │
                        ▼
                  ┌───────────┐
                  │PostgreSQL │
                  └───────────┘
```

---

## 4. Project Structure

```
fastrecce/
├── docs/                          # Architecture docs (this folder)
│   ├── module-breakdown.md
│   ├── system-architecture.md
│   ├── database-schema.md
│   └── api-spec.md
│
├── backend/                       # Python backend (both units)
│   ├── alembic/                   # Database migrations
│   │   ├── versions/
│   │   └── alembic.ini
│   │
│   ├── app/                       # Application code
│   │   ├── __init__.py
│   │   ├── config.py              # Settings via pydantic-settings
│   │   ├── database.py            # SQLAlchemy engine, session factory
│   │   │
│   │   ├── models/                # SQLAlchemy ORM models (DB layer)
│   │   │   ├── __init__.py
│   │   │   ├── property.py        # Property, PropertySource, PropertyContact
│   │   │   ├── media.py           # PropertyMedia
│   │   │   ├── source.py          # Source registry
│   │   │   ├── query.py           # Query bank
│   │   │   ├── crawl.py           # CrawlRun, PropertyChange
│   │   │   ├── outreach.py        # OutreachQueue
│   │   │   └── user.py            # User, roles
│   │   │
│   │   ├── schemas/               # Pydantic schemas (API layer)
│   │   │   ├── __init__.py
│   │   │   ├── property.py
│   │   │   ├── outreach.py
│   │   │   ├── query.py
│   │   │   └── pipeline.py
│   │   │
│   │   ├── services/              # Business logic (core layer)
│   │   │   ├── __init__.py
│   │   │   ├── discovery.py       # M3: Google Places discovery
│   │   │   ├── crawler.py         # M4: Website crawl & extraction
│   │   │   ├── extractors/        # M4: Sub-components
│   │   │   │   ├── __init__.py
│   │   │   │   ├── structured.py  # Schema.org, JSON-LD, tel/mailto
│   │   │   │   ├── unstructured.py# Free text, about sections
│   │   │   │   └── media.py       # Image URLs, hashes
│   │   │   ├── contacts.py        # M5: Contact resolution
│   │   │   ├── dedup.py           # M6: Deduplication
│   │   │   ├── scoring.py         # M7: Relevance scoring
│   │   │   ├── briefing.py        # M8: AI brief generation
│   │   │   └── outreach.py        # Outreach queue management
│   │   │
│   │   ├── api/                   # FastAPI routes (UNIT 2)
│   │   │   ├── __init__.py
│   │   │   ├── main.py            # FastAPI app factory
│   │   │   ├── deps.py            # Dependency injection (DB session, auth)
│   │   │   ├── properties.py      # Property CRUD + review endpoints
│   │   │   ├── outreach.py        # Outreach queue endpoints
│   │   │   ├── queries.py         # Query bank management
│   │   │   ├── pipeline.py        # Pipeline health & run status
│   │   │   ├── sources.py         # Source registry CRUD
│   │   │   └── auth.py            # Login, user management
│   │   │
│   │   ├── pipeline/              # Pipeline orchestration (UNIT 1)
│   │   │   ├── __init__.py
│   │   │   ├── daily.py           # Daily pipeline DAG
│   │   │   ├── weekly.py          # Weekly pipeline DAG
│   │   │   ├── tasks.py           # Individual pipeline tasks
│   │   │   └── scheduler.py       # Prefect/APScheduler config
│   │   │
│   │   └── integrations/          # External service clients
│   │       ├── __init__.py
│   │       ├── google_places.py   # Google Places API client
│   │       ├── llm.py             # Gemini API client for briefs/scoring
│   │       └── storage.py         # S3-compatible storage client
│   │
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── conftest.py
│   │
│   ├── pyproject.toml             # Dependencies (uv/poetry)
│   ├── Dockerfile
│   └── .env.example
│
├── frontend/                      # React SPA (UNIT 2 client)
│   ├── src/
│   │   ├── api/                   # API client (generated from OpenAPI or manual)
│   │   │   ├── client.ts
│   │   │   └── types.ts
│   │   ├── components/            # Reusable UI components
│   │   │   ├── ui/                # shadcn/ui primitives
│   │   │   ├── PropertyCard.tsx
│   │   │   ├── ScoreBreakdown.tsx
│   │   │   ├── ContactList.tsx
│   │   │   └── OutreachKanban.tsx
│   │   ├── pages/                 # Route-level pages
│   │   │   ├── LeadQueue.tsx
│   │   │   ├── PropertyDetail.tsx
│   │   │   ├── OutreachPipeline.tsx
│   │   │   ├── PipelineHealth.tsx
│   │   │   ├── QueryManager.tsx
│   │   │   └── Login.tsx
│   │   ├── hooks/                 # Custom React hooks
│   │   ├── lib/                   # Utilities
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   └── vite.config.ts
│
├── docker-compose.yml             # Local dev: PostgreSQL + Redis + MinIO
├── .github/
│   └── workflows/
│       └── ci.yml
└── README.md
```

### Why This Structure

| Decision | Reasoning |
|---|---|
| **Single repo (monorepo)** | Small team, shared types between pipeline and API, simpler CI. Split later if needed. |
| **`models/` separate from `schemas/`** | Models = database layer (SQLAlchemy). Schemas = API layer (Pydantic). Never expose ORM models directly in API responses. |
| **`services/` owns all business logic** | Controllers (api/) are thin — validate input, call service, return response. Services are testable without HTTP. |
| **`pipeline/` separate from `api/`** | Different entry points, different runtime. Pipeline imports services, API imports services. Services don't know about either. |
| **`integrations/` for external clients** | Google Places, Gemini API, S3 — all behind clean interfaces. Easy to mock in tests, easy to swap providers. |
| **`extractors/` as sub-package** | Crawl module has distinct sub-components (structured, unstructured, media). Each is independently testable. |

---

## 5. Communication Patterns

### Between Pipeline and Dashboard

No direct communication. Both read/write to **shared PostgreSQL**. This is intentional:

- Pipeline writes new properties, scores, and briefs to the DB
- Dashboard reads them on each page load (TanStack Query handles caching/refetch)
- Reviewer actions (approve, reject, assign) write to DB
- Pipeline reads reviewer feedback for scoring recalibration

**No WebSockets or event bus needed at MVP.** Dashboard users can refresh or poll. If real-time updates become important later, add a `pg_notify` → WebSocket bridge.

### Between Pipeline Stages

**In-process function calls**, not message queues. The daily pipeline is a sequential DAG:

```python
# pipeline/daily.py (simplified)
async def run_daily_pipeline(cities: list[str]):
    # Stage 1: Discovery
    candidates = await discovery_service.discover(cities)

    # Stage 2: Dedup filter
    new_candidates = await dedup_service.filter_known(candidates)

    # Stage 3: Crawl & Extract
    for candidate in new_candidates:
        crawl_result = await crawler_service.crawl(candidate)
        contacts = await contact_service.resolve(crawl_result)
        property = await property_service.upsert(candidate, crawl_result, contacts)

    # Stage 4: Score & Brief (batch)
    unscored = await property_service.get_unscored()
    await scoring_service.score_batch(unscored)
    await briefing_service.generate_batch(unscored)
```

**Why not a message queue between stages?** At MVP scale (hundreds of properties/day), the overhead of serializing/deserializing through Redis queues adds complexity without benefit. The pipeline runs sequentially in ~10-30 minutes. If it needs to scale to tens of thousands of properties, introduce arq task queues between stages.

### Between Frontend and Backend

Standard REST API over HTTPS. JSON request/response bodies.

- **Authentication:** JWT tokens (simple, stateless)
- **Pagination:** Cursor-based for lead queue (properties ordered by score)
- **Filtering:** Query params for city, property_type, score_range, status
- **No GraphQL:** Overkill for an internal tool with a small, known set of views

---

## 6. External Integration Architecture

```
┌─────────────────────────────────────────────────────┐
│                    FastRecce System                   │
│                                                       │
│  ┌───────────────┐    ┌────────────────────────┐     │
│  │ Google Places │    │   Property Websites    │     │
│  │ Client        │    │   Crawler              │     │
│  │               │    │                        │     │
│  │ - Text Search │    │ - httpx (static pages) │     │
│  │ - Place Detail│    │ - Playwright (JS)      │     │
│  │ - Rate Limiter│    │ - robots.txt check     │     │
│  └───────┬───────┘    └──────────┬─────────────┘     │
│          │                       │                    │
│          ▼                       ▼                    │
│  ┌─────────────────────────────────────────────┐     │
│  │              Services Layer                  │     │
│  └──────────────────┬──────────────────────────┘     │
│                     │                                 │
│          ┌──────────┼──────────┐                     │
│          ▼          ▼          ▼                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐             │
│  │Gemini API│ │PostgreSQL│ │   S3     │             │
│  │(Briefs)  │ │(Entities)│ │(Snapshot)│             │
│  └──────────┘ └──────────┘ └──────────┘             │
└─────────────────────────────────────────────────────┘
```

### API Rate Limiting Strategy

| Service | Limit | Strategy |
|---|---|---|
| **Google Places Text Search** | Varies by billing (up to 50k requests/month at basic tier) | Token bucket rate limiter in Redis. Batch queries by city. Cache results for 24h. |
| **Google Places Details** | Same billing as above | Fetch only for new place_ids not already in DB. |
| **Property Websites** | No API limit, but be polite | Max 2 concurrent requests per domain. 1-2 second delay between requests. Respect robots.txt. |
| **Gemini API** | Based on tier | Batch brief generation. Use context caching for the system prompt. Fallback to template if rate-limited. |

### Integration Isolation

Each external service has a dedicated client class in `integrations/`:

```
integrations/
├── google_places.py   # GooglePlacesClient
├── llm.py             # LLMClient (Gemini)
└── storage.py         # StorageClient (S3)
```

**Why:** If Google Places API changes or we add a second discovery source (e.g., Booking.com Connectivity API in Phase 2), only the client class changes. Services call `discovery_client.search()`, not `google_places.text_search()`.

---

## 7. Data Storage Strategy

### What Goes Where

| Data Type | Storage | Retention | Why |
|---|---|---|---|
| Canonical property entities | PostgreSQL | Permanent | Core business data |
| Property sources & contacts | PostgreSQL | Permanent | Audit trail |
| Scores & briefs | PostgreSQL | Permanent (recomputed) | Query + display on dashboard |
| Crawl run metadata | PostgreSQL | 1 year | Operational observability |
| Property change history | PostgreSQL | 6 months | Change detection audit |
| Raw HTML snapshots | S3 | 90 days | Debug & re-extraction if parsers improve |
| Media files / images | S3 | 90 days (or permanent for onboarded) | Referenced by URL, heavy |
| Dedup cache (place_id set) | Redis | Persistent (RDB) | Fast lookup during discovery |
| Rate limit counters | Redis | TTL-based | Transient |
| Job queue state | Redis | Transient | Pipeline task management |

### PostgreSQL Extensions

| Extension | Purpose |
|---|---|
| **PostGIS** | Geo distance queries for dedup (properties within 200m of each other) |
| **pg_trgm** | Trigram similarity for fuzzy name matching in dedup |
| **pgcrypto** | UUID generation for primary keys |

---

## 8. Security Architecture

### Authentication & Authorization

| Concern | Approach |
|---|---|
| **Auth method** | Email/password with JWT (internal tool, no OAuth complexity needed) |
| **Token type** | Short-lived access token (15 min) + refresh token (7 days) |
| **Roles** | `admin` (full access), `reviewer` (review + outreach), `viewer` (read-only) |
| **API protection** | All endpoints require valid JWT except `/auth/login` |
| **CORS** | Restricted to frontend domain only |

### Data Security

| Concern | Approach |
|---|---|
| **API keys** | Google Places key, Gemini key stored in env vars. Never in code or DB. |
| **Contact data** | Only public business contacts stored. Personal contacts flagged, not auto-stored. |
| **Audit trail** | Every contact has `source_url` and `source_name`. Full provenance. |
| **Do-not-contact** | Maintained in DB. Checked before any outreach action. Cannot be overridden without admin role. |

---

## 9. Error Handling & Resilience

### Pipeline Resilience

| Failure | Strategy |
|---|---|
| Google API timeout | Retry 3x with exponential backoff (1s, 4s, 16s). Skip query after 3 failures. |
| Google API quota exhausted | Stop discovery stage. Process already-discovered candidates. Alert admin. |
| Website crawl timeout | 30s timeout per page. Mark property as `crawl_failed`. Continue pipeline. |
| Website returns 403/404 | Log and skip. Don't retry (likely blocked or dead). Mark for dead-link cleanup. |
| Playwright crash | Restart browser context. Retry once. Fall back to static fetch. |
| LLM API failure | Use template-based brief fallback. Queue for LLM retry in next run. |
| Database connection lost | Pipeline stage retries with backoff. Dashboard returns 503. |
| Dedup false positive | Surface as "duplicate warning" on dashboard. Human decides. |

### Idempotency

Every pipeline stage is idempotent:

- Discovery: `place_id` is the dedup key. Re-running the same query produces the same candidates.
- Crawl: `snapshot_hash` detects unchanged content. No reprocessing.
- Upsert: Properties are upserted on `(normalized_name, city, lat/lng)` composite key.
- Scoring: Deterministic formula. Same inputs → same score.
- Briefs: Regenerated only when property data hash changes.

---

## 10. Deployment Architecture (MVP)

### Local Development

```
docker-compose.yml
├── postgresql:16 (port 5432)
├── redis:7 (port 6379)
└── minio (port 9000)    # S3-compatible local storage

# Run separately:
# Terminal 1: uvicorn app.api.main:app --reload (Dashboard API)
# Terminal 2: python -m app.pipeline.daily      (Pipeline, manual trigger)
# Terminal 3: cd frontend && npm run dev         (React SPA)
```

### Production (MVP)

```
┌──────────────────────────────────────────────┐
│              Single VPS / Railway             │
│                                               │
│  ┌─────────────┐     ┌─────────────────┐     │
│  │ FastAPI     │     │ Pipeline Worker │     │
│  │ (gunicorn)  │     │ (Prefect agent) │     │
│  │ Port 8000   │     │ Cron-triggered  │     │
│  └──────┬──────┘     └────────┬────────┘     │
│         │                     │               │
│         └─────────┬───────────┘               │
│                   │                           │
│         ┌─────────▼─────────┐                │
│         │   PostgreSQL 16   │                │
│         │   + PostGIS       │                │
│         └───────────────────┘                │
│         ┌───────────────────┐                │
│         │     Redis 7       │                │
│         └───────────────────┘                │
│                                               │
│  ┌───────────────────────────┐               │
│  │ React SPA (static files) │               │
│  │ Served by Nginx / CDN    │               │
│  └───────────────────────────┘               │
└──────────────────────────────────────────────┘
```

### Scaling Path (Post-MVP)

| Trigger | Action |
|---|---|
| Pipeline takes >1 hour | Parallelize crawl stage with arq worker pool |
| >10 concurrent dashboard users | Horizontal API instances behind load balancer |
| >50k properties in DB | Add PostgreSQL read replicas for dashboard queries |
| Multi-region expansion | Separate pipeline workers per region to reduce crawl latency |

---

## 11. Key Architectural Trade-offs

| Decision | Trade-off | Why We Accept It |
|---|---|---|
| Modular monolith over microservices | Less isolation between modules | Team is small. Operational simplicity > isolation at this scale. |
| Shared DB between pipeline and dashboard | Schema coupling | Same team owns both. Single source of truth is simpler than event sync. |
| Sequential pipeline over parallel tasks | Slower pipeline execution | At MVP volume (<2000 properties/day), sequential finishes in <30 min. Add parallelism when it hurts. |
| PostgreSQL full-text search over Elasticsearch | Less powerful search | Dashboard search is simple (city, type, name). Don't add infra for a problem we don't have yet. |
| JWT over session-based auth | No server-side session invalidation | Internal tool with small user base. Acceptable trade-off for stateless simplicity. |
| Prefect over Airflow | Smaller community, less battle-tested | Much lighter weight. Airflow is overkill for 3 pipeline DAGs. Migrate if needed. |

---

*Next Step: Database Schema Design → `/docs/database-schema.md`*

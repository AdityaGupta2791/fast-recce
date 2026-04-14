# FastRecce Platform — Database Schema Design

> **Document Version:** 1.0
> **Date:** 2026-04-13
> **Status:** Draft — Pending Confirmation
> **Depends On:** [module-breakdown.md](./module-breakdown.md), [system-architecture.md](./system-architecture.md)

---

## 1. Design Principles

| Principle | Application |
|---|---|
| **Canonical entity model** | One `properties` row per real-world property. Multiple source records link to it. Never one-row-per-scrape. |
| **Full provenance** | Every piece of contact data traces back to a source URL and extraction date. |
| **Idempotent upserts** | Pipeline can re-run safely. Natural keys prevent duplicates. |
| **Query-driven indexing** | Indexes are designed for known access patterns, not speculative. |
| **JSONB for flexibility, columns for filterability** | If the dashboard filters on it, it's a column. If it's raw/debug data, it's JSONB. |
| **Soft delete where needed** | Properties and contacts are never hard-deleted — marked with status flags for audit. |

---

## 2. Required PostgreSQL Extensions

```sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";      -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "postgis";        -- Geography type, ST_DWithin
CREATE EXTENSION IF NOT EXISTS "pg_trgm";        -- Trigram similarity for fuzzy name match
```

---

## 3. Enum Types (as CHECK constraints)

We use VARCHAR + CHECK constraints instead of PostgreSQL ENUM types. Rationale: adding a value to a PG enum requires `ALTER TYPE ... ADD VALUE` which cannot run inside a transaction in older PG versions and is awkward in migrations. CHECK constraints are trivially alterable.

```
source_type:       'api' | 'website' | 'manual' | 'partner_feed'
access_policy:     'allowed' | 'manual_only' | 'restricted'
crawl_method:      'api_call' | 'sitemap' | 'html_parser' | 'browser_render'
property_type:     'boutique_hotel' | 'villa' | 'bungalow' | 'heritage_home' | 'farmhouse' |
                   'resort' | 'banquet_hall' | 'cafe' | 'restaurant' | 'warehouse' |
                   'industrial_shed' | 'office_space' | 'school_campus' | 'coworking_space' |
                   'rooftop_venue' | 'theatre_studio' | 'club_lounge' | 'other'
contact_type:      'phone' | 'email' | 'whatsapp' | 'form' | 'website' | 'instagram'
media_type:        'image' | 'video' | 'virtual_tour'
crawl_status:      'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
property_status:   'new' | 'reviewed' | 'approved' | 'rejected' | 'onboarded' | 'do_not_contact'
outreach_status:   'pending' | 'contacted' | 'responded' | 'follow_up' | 'converted' |
                   'declined' | 'no_response'
change_type:       'created' | 'contact_updated' | 'score_changed' | 'merged' | 'manual_edit'
user_role:         'admin' | 'reviewer' | 'sales' | 'viewer'
```

---

## 4. Table Definitions

### 4.1 `users`

**Module:** Cross-cutting (Dashboard auth)
**Purpose:** Internal team members who use the dashboard.

```sql
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    full_name       VARCHAR(255) NOT NULL,
    role            VARCHAR(20)  NOT NULL DEFAULT 'viewer'
                    CHECK (role IN ('admin', 'reviewer', 'sales', 'viewer')),
    is_active       BOOLEAN      NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
```

**Indexes:**
```sql
-- Login lookup
CREATE UNIQUE INDEX idx_users_email ON users (email);
```

**Notes:**
- Small table (~10-50 rows). No complex indexing needed.
- `password_hash` uses bcrypt via passlib.
- No profile photos or social login — internal tool.

---

### 4.2 `sources`

**Module:** M1 (Source Registry)
**Purpose:** Defines every data source and how the system should interact with it.

```sql
CREATE TABLE sources (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name         VARCHAR(100) NOT NULL UNIQUE,
    source_type         VARCHAR(20)  NOT NULL
                        CHECK (source_type IN ('api', 'website', 'manual', 'partner_feed')),
    access_policy       VARCHAR(20)  NOT NULL DEFAULT 'allowed'
                        CHECK (access_policy IN ('allowed', 'manual_only', 'restricted')),
    crawl_method        VARCHAR(20)  NOT NULL
                        CHECK (crawl_method IN ('api_call', 'sitemap', 'html_parser', 'browser_render')),
    base_url            VARCHAR(500),
    refresh_frequency   VARCHAR(20)  NOT NULL DEFAULT 'daily',
    parser_version      VARCHAR(20)  NOT NULL DEFAULT '1.0',
    rate_limit_rpm      INTEGER      NOT NULL DEFAULT 60,
    is_enabled          BOOLEAN      NOT NULL DEFAULT true,
    notes               TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);
```

**Indexes:**
```sql
-- Pipeline looks up enabled sources by type
CREATE INDEX idx_sources_enabled_type ON sources (source_type) WHERE is_enabled = true;
```

**Seed data (Phase 1 sources):**
| source_name | source_type | access_policy | crawl_method |
|---|---|---|---|
| google_places | api | allowed | api_call |
| property_website | website | allowed | html_parser |
| maharera | website | allowed | html_parser |
| airbnb | website | restricted | browser_render |
| magicbricks | website | restricted | browser_render |
| 99acres | website | restricted | browser_render |
| peerspace | website | restricted | browser_render |
| manual_import | manual | allowed | — |

---

### 4.3 `query_bank`

**Module:** M2 (Query Bank)
**Purpose:** Search queries that drive discovery. Managed entity with performance tracking.

```sql
CREATE TABLE query_bank (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text      VARCHAR(500) NOT NULL,
    city            VARCHAR(100) NOT NULL,
    locality        VARCHAR(100),
    property_type   VARCHAR(50)  NOT NULL
                    CHECK (property_type IN (
                        'boutique_hotel', 'villa', 'bungalow', 'heritage_home', 'farmhouse',
                        'resort', 'banquet_hall', 'cafe', 'restaurant', 'warehouse',
                        'industrial_shed', 'office_space', 'school_campus', 'coworking_space',
                        'rooftop_venue', 'theatre_studio', 'club_lounge', 'other'
                    )),
    segment_tags    JSONB        NOT NULL DEFAULT '[]',
    is_enabled      BOOLEAN      NOT NULL DEFAULT true,
    last_run_at     TIMESTAMPTZ,
    total_runs      INTEGER      NOT NULL DEFAULT 0,
    total_results   INTEGER      NOT NULL DEFAULT 0,
    new_properties  INTEGER      NOT NULL DEFAULT 0,
    quality_score   REAL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),

    UNIQUE (query_text, city)
);
```

**Indexes:**
```sql
-- Discovery engine fetches enabled queries by city
CREATE INDEX idx_query_bank_city_enabled ON query_bank (city) WHERE is_enabled = true;

-- Dashboard: query performance analysis
CREATE INDEX idx_query_bank_quality ON query_bank (quality_score DESC NULLS LAST);
```

**Notes:**
- `segment_tags` is JSONB array: `["premium", "outdoor", "residential"]` — flexible tagging without a join table.
- `quality_score` = `new_properties / total_results` ratio. High quality = discovers new properties. Low quality = returns only known ones.
- `UNIQUE (query_text, city)` prevents duplicate queries.

---

### 4.4 `properties`

**Module:** Core entity — touched by M3-M9
**Purpose:** The canonical record for each real-world property. One row per property.

```sql
CREATE TABLE properties (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name      VARCHAR(500) NOT NULL,
    normalized_name     VARCHAR(500) NOT NULL,
    normalized_address  VARCHAR(1000),
    city                VARCHAR(100) NOT NULL,
    locality            VARCHAR(200),
    state               VARCHAR(100),
    pincode             VARCHAR(10),
    location            GEOGRAPHY(POINT, 4326),
    lat                 DOUBLE PRECISION,
    lng                 DOUBLE PRECISION,
    property_type       VARCHAR(50)  NOT NULL
                        CHECK (property_type IN (
                            'boutique_hotel', 'villa', 'bungalow', 'heritage_home', 'farmhouse',
                            'resort', 'banquet_hall', 'cafe', 'restaurant', 'warehouse',
                            'industrial_shed', 'office_space', 'school_campus', 'coworking_space',
                            'rooftop_venue', 'theatre_studio', 'club_lounge', 'other'
                        )),
    status              VARCHAR(20)  NOT NULL DEFAULT 'new'
                        CHECK (status IN ('new', 'reviewed', 'approved', 'rejected', 'onboarded', 'do_not_contact')),

    -- Canonical contact (best-known contact from property_contacts)
    canonical_website   VARCHAR(500),
    canonical_phone     VARCHAR(50),
    canonical_email     VARCHAR(255),

    -- AI-generated content
    short_brief         TEXT,
    brief_generated_at  TIMESTAMPTZ,

    -- Scoring
    relevance_score     REAL         DEFAULT 0.0 CHECK (relevance_score >= 0 AND relevance_score <= 1),
    score_reason_json   JSONB,
    scored_at           TIMESTAMPTZ,

    -- Features extracted from crawl
    features_json       JSONB        NOT NULL DEFAULT '{}',

    -- Metadata
    google_place_id     VARCHAR(300),
    google_rating       REAL,
    google_review_count INTEGER,
    duplicate_of        UUID         REFERENCES properties(id),
    is_duplicate        BOOLEAN      NOT NULL DEFAULT false,

    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);
```

**Indexes:**
```sql
-- PRIMARY dashboard query: list by score, filtered by city + type + status
CREATE INDEX idx_properties_dashboard
    ON properties (city, property_type, status, relevance_score DESC);

-- Geo-spatial dedup: find properties within N meters
CREATE INDEX idx_properties_location
    ON properties USING GIST (location);

-- Fuzzy name matching for dedup (trigram)
CREATE INDEX idx_properties_normalized_name_trgm
    ON properties USING GIN (normalized_name gin_trgm_ops);

-- Google Place ID lookup (discovery dedup)
CREATE UNIQUE INDEX idx_properties_google_place_id
    ON properties (google_place_id) WHERE google_place_id IS NOT NULL;

-- Phone-based dedup
CREATE INDEX idx_properties_phone
    ON properties (canonical_phone) WHERE canonical_phone IS NOT NULL;

-- Website domain dedup
CREATE INDEX idx_properties_website
    ON properties (canonical_website) WHERE canonical_website IS NOT NULL;

-- Pipeline: find properties needing scoring
CREATE INDEX idx_properties_unscored
    ON properties (created_at) WHERE scored_at IS NULL;

-- Pipeline: find properties needing briefs
CREATE INDEX idx_properties_unbriefed
    ON properties (scored_at) WHERE brief_generated_at IS NULL AND scored_at IS NOT NULL;

-- Duplicate chain
CREATE INDEX idx_properties_duplicate_of
    ON properties (duplicate_of) WHERE duplicate_of IS NOT NULL;
```

**Key Design Decisions:**

| Decision | Reasoning |
|---|---|
| `normalized_name` separate from `canonical_name` | `canonical_name` is the display name ("The Oberoi, Mumbai"). `normalized_name` is lowercase, stripped of punctuation ("oberoi mumbai") — used for dedup matching only. |
| `location` as PostGIS GEOGRAPHY | Enables `ST_DWithin(a.location, b.location, 200)` for "properties within 200m" dedup queries. `lat`/`lng` columns kept for convenience and non-geo queries. |
| `features_json` as JSONB | Property features vary wildly (amenities, room count, lawn size, parking, aesthetic tags). Structured differently per property type. Not worth normalizing into columns. |
| `duplicate_of` self-referential FK | When a property is marked duplicate, it points to the canonical record it was merged into. Enables "show me all records that were merged into this one." |
| `score_reason_json` structure | `{"type_fit": 0.8, "shoot_fit": 0.7, "visual_uniqueness": 0.6, ...}` — each sub-score stored so dashboard can render the breakdown. |
| Partial indexes for pipeline queries | `WHERE scored_at IS NULL` targets only the rows the pipeline needs. At 50k properties, this keeps pipeline queries fast even without vacuuming. |

---

### 4.5 `property_sources`

**Module:** M3 (Discovery), M4 (Crawl)
**Purpose:** Links a canonical property to every source it was discovered from. Preserves full source history.

```sql
CREATE TABLE property_sources (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id         UUID         NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    source_name         VARCHAR(100) NOT NULL,
    source_url          VARCHAR(2000),
    external_id         VARCHAR(300),
    query_id            UUID         REFERENCES query_bank(id),
    discovered_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    raw_title           VARCHAR(1000),
    raw_description     TEXT,
    raw_contact_json    JSONB,
    raw_features_json   JSONB,
    raw_snapshot_hash   VARCHAR(64),
    raw_snapshot_path   VARCHAR(500),
    is_primary          BOOLEAN      NOT NULL DEFAULT false,

    UNIQUE (source_name, external_id)
);
```

**Indexes:**
```sql
-- Find all sources for a property
CREATE INDEX idx_property_sources_property ON property_sources (property_id);

-- Discovery dedup: check if external_id already exists
CREATE UNIQUE INDEX idx_property_sources_ext_id
    ON property_sources (source_name, external_id) WHERE external_id IS NOT NULL;

-- Pipeline: find sources not seen recently (stale detection)
CREATE INDEX idx_property_sources_last_seen ON property_sources (last_seen_at);
```

**Notes:**
- `UNIQUE (source_name, external_id)` prevents the same Google Place ID from creating duplicate source records.
- `is_primary` marks the best/most-trusted source for a property. Used to pick canonical contacts.
- `raw_snapshot_path` points to S3 for the archived HTML.
- `raw_snapshot_hash` (SHA-256) enables change detection without re-downloading.

---

### 4.6 `property_contacts`

**Module:** M5 (Contact Resolution)
**Purpose:** All contact information for a property, with full provenance and compliance flags.

```sql
CREATE TABLE property_contacts (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id                 UUID         NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    contact_type                VARCHAR(20)  NOT NULL
                                CHECK (contact_type IN ('phone', 'email', 'whatsapp', 'form', 'website', 'instagram')),
    contact_value               VARCHAR(500) NOT NULL,
    normalized_value            VARCHAR(500) NOT NULL,
    source_name                 VARCHAR(100) NOT NULL,
    source_url                  VARCHAR(2000),
    extraction_method           VARCHAR(50),
    confidence                  REAL         NOT NULL DEFAULT 0.5
                                CHECK (confidence >= 0 AND confidence <= 1),
    is_public_business_contact  BOOLEAN      NOT NULL DEFAULT false,
    is_verified                 BOOLEAN      NOT NULL DEFAULT false,
    is_primary                  BOOLEAN      NOT NULL DEFAULT false,
    flagged_personal            BOOLEAN      NOT NULL DEFAULT false,
    first_seen_at               TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_seen_at                TIMESTAMPTZ  NOT NULL DEFAULT now(),

    UNIQUE (property_id, contact_type, normalized_value)
);
```

**Indexes:**
```sql
-- Property detail page: list contacts for a property
CREATE INDEX idx_contacts_property ON property_contacts (property_id);

-- Dedup: find properties sharing the same phone number
CREATE INDEX idx_contacts_phone_dedup
    ON property_contacts (normalized_value)
    WHERE contact_type = 'phone';

-- Dedup: find properties sharing the same email
CREATE INDEX idx_contacts_email_dedup
    ON property_contacts (normalized_value)
    WHERE contact_type = 'email';

-- Compliance: find flagged personal contacts needing review
CREATE INDEX idx_contacts_flagged
    ON property_contacts (flagged_personal)
    WHERE flagged_personal = true;
```

**Notes:**
- `normalized_value` for phones: strip spaces, dashes, country code → `919876543210`. For emails: lowercase + trim.
- `UNIQUE (property_id, contact_type, normalized_value)` prevents duplicate contact rows for the same property.
- `extraction_method`: `'api_structured'`, `'html_tel_link'`, `'html_mailto'`, `'text_regex'`, `'schema_org'`, `'manual'` — tells you *how* the contact was found.
- `confidence` scoring: API-sourced phone (0.95) > tel link on contact page (0.85) > regex-matched email in text (0.6).
- `flagged_personal`: true if contact matches personal patterns (gmail/yahoo/mobile-only). Requires manual review before use.

---

### 4.7 `property_media`

**Module:** M4 (Crawl/Extract)
**Purpose:** Images and media collected from property websites and APIs.

```sql
CREATE TABLE property_media (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id     UUID         NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    media_url       VARCHAR(2000) NOT NULL,
    media_type      VARCHAR(20)  NOT NULL DEFAULT 'image'
                    CHECK (media_type IN ('image', 'video', 'virtual_tour')),
    source_name     VARCHAR(100) NOT NULL,
    alt_text        VARCHAR(500),
    image_hash      VARCHAR(64),
    width           INTEGER,
    height          INTEGER,
    s3_path         VARCHAR(500),
    sort_order      INTEGER      NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),

    UNIQUE (property_id, media_url)
);
```

**Indexes:**
```sql
-- Property detail: load media for a property
CREATE INDEX idx_media_property ON property_media (property_id, sort_order);

-- Dedup: find similar images across properties (perceptual hash)
CREATE INDEX idx_media_hash ON property_media (image_hash) WHERE image_hash IS NOT NULL;
```

**Notes:**
- `image_hash` is a perceptual hash (pHash or dHash), not a cryptographic hash. Enables "find visually similar images" for dedup.
- `s3_path` is populated only if the image is archived to S3 (for high-priority properties). Most images are referenced by URL only.
- `UNIQUE (property_id, media_url)` prevents storing the same image twice for one property.

---

### 4.8 `crawl_runs`

**Module:** M10 (Orchestrator), M4 (Crawl)
**Purpose:** Audit trail of every pipeline execution. Powers the Pipeline Health dashboard view.

```sql
CREATE TABLE crawl_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_type            VARCHAR(20)  NOT NULL DEFAULT 'daily'
                        CHECK (run_type IN ('daily', 'weekly', 'monthly', 'manual')),
    source_name         VARCHAR(100),
    city                VARCHAR(100),
    status              VARCHAR(20)  NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    started_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    duration_seconds    INTEGER,

    -- Counters
    queries_executed    INTEGER      NOT NULL DEFAULT 0,
    urls_processed      INTEGER      NOT NULL DEFAULT 0,
    new_properties      INTEGER      NOT NULL DEFAULT 0,
    updated_properties  INTEGER      NOT NULL DEFAULT 0,
    skipped_duplicates  INTEGER      NOT NULL DEFAULT 0,
    crawl_errors        INTEGER      NOT NULL DEFAULT 0,

    -- Details
    errors_json         JSONB        NOT NULL DEFAULT '[]',
    config_json         JSONB,
    notes               TEXT
);
```

**Indexes:**
```sql
-- Dashboard: recent runs
CREATE INDEX idx_crawl_runs_started ON crawl_runs (started_at DESC);

-- Filter by status (find failed runs)
CREATE INDEX idx_crawl_runs_status ON crawl_runs (status) WHERE status IN ('failed', 'running');
```

---

### 4.9 `property_changes`

**Module:** M4 (Crawl — change detection)
**Purpose:** Tracks changes to property data over time. Enables "what changed since last crawl" auditing.

```sql
CREATE TABLE property_changes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id     UUID         NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    change_type     VARCHAR(30)  NOT NULL
                    CHECK (change_type IN ('created', 'contact_updated', 'score_changed', 'merged', 'manual_edit')),
    field_name      VARCHAR(100),
    before_value    TEXT,
    after_value     TEXT,
    changed_by      UUID         REFERENCES users(id),
    crawl_run_id    UUID         REFERENCES crawl_runs(id),
    detected_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);
```

**Indexes:**
```sql
-- Property detail: change history
CREATE INDEX idx_changes_property ON property_changes (property_id, detected_at DESC);

-- Pipeline: changes from a specific run
CREATE INDEX idx_changes_crawl_run ON property_changes (crawl_run_id);
```

**Notes:**
- Granular field-level change tracking. `field_name = 'canonical_phone'`, `before_value = '9876543210'`, `after_value = '9876543211'`.
- `changed_by` is NULL for pipeline-detected changes, populated for manual edits via dashboard.
- Retention: 6 months. Older records purged by weekly cleanup job.

---

### 4.10 `outreach_queue`

**Module:** M9 (Dashboard — Outreach Pipeline)
**Purpose:** Manages the outreach workflow from approved lead to conversion.

```sql
CREATE TABLE outreach_queue (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id         UUID         NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    assigned_to         UUID         REFERENCES users(id),
    status              VARCHAR(20)  NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'contacted', 'responded', 'follow_up', 'converted', 'declined', 'no_response')),
    priority            INTEGER      NOT NULL DEFAULT 50
                        CHECK (priority >= 1 AND priority <= 100),
    outreach_channel    VARCHAR(20)
                        CHECK (outreach_channel IN ('phone', 'email', 'whatsapp', 'form', 'in_person')),
    suggested_angle     TEXT,
    first_contact_at    TIMESTAMPTZ,
    last_contact_at     TIMESTAMPTZ,
    follow_up_at        TIMESTAMPTZ,
    contact_attempts    INTEGER      NOT NULL DEFAULT 0,
    notes               TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),

    UNIQUE (property_id)
);
```

**Indexes:**
```sql
-- Outreach pipeline view: by assignment and status
CREATE INDEX idx_outreach_assigned_status
    ON outreach_queue (assigned_to, status);

-- Priority queue: highest priority pending items
CREATE INDEX idx_outreach_priority
    ON outreach_queue (priority DESC, created_at)
    WHERE status = 'pending';

-- Follow-up reminders
CREATE INDEX idx_outreach_follow_up
    ON outreach_queue (follow_up_at)
    WHERE follow_up_at IS NOT NULL AND status IN ('contacted', 'follow_up');
```

**Notes:**
- `UNIQUE (property_id)` — one outreach record per property. Not one-per-attempt. Contact attempts tracked as a counter + notes.
- `priority` derived from `relevance_score` but can be manually overridden by reviewers.
- `suggested_angle` is AI-generated: "This property has hosted brand events before — lead with FastRecce's managed booking proposition."

---

### 4.11 `do_not_contact`

**Module:** M8 (Compliance — cross-cutting)
**Purpose:** Blocklist for contacts that must never be reached out to.

```sql
CREATE TABLE do_not_contact (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_type    VARCHAR(20)  NOT NULL
                    CHECK (contact_type IN ('phone', 'email', 'whatsapp', 'domain')),
    contact_value   VARCHAR(500) NOT NULL,
    reason          TEXT         NOT NULL,
    added_by        UUID         NOT NULL REFERENCES users(id),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),

    UNIQUE (contact_type, contact_value)
);
```

**Indexes:**
```sql
-- Compliance check: is this contact blocked?
CREATE UNIQUE INDEX idx_dnc_lookup
    ON do_not_contact (contact_type, contact_value);
```

---

## 5. Entity Relationship Diagram

```
                                    ┌──────────┐
                                    │  users   │
                                    └────┬─────┘
                                         │ (assigned_to, changed_by, added_by)
                                         │
┌───────────┐    ┌──────────────┐   ┌────┴──────────┐    ┌──────────────────┐
│  sources  │    │  query_bank  │   │  properties   │───▶│ property_sources │
│           │    │              │   │               │    │                  │
│ (config)  │    │ (discovery   │   │ (canonical    │    │ (source history) │
│           │    │  queries)    │   │  entity)      │    └──────────────────┘
└───────────┘    └──────┬───────┘   │               │
                        │           │               │───▶┌──────────────────┐
                        │           │               │    │property_contacts │
                        └──────────▶│               │    │                  │
                         (query_id) │               │    │ (all contacts)   │
                                    │               │    └──────────────────┘
                                    │               │
                                    │               │───▶┌──────────────────┐
                                    │               │    │ property_media   │
                                    │               │    └──────────────────┘
                                    │               │
                                    │               │───▶┌──────────────────┐
                                    │               │    │property_changes  │
                                    │               │    └──────────────────┘
                                    │               │
                                    │               │───▶┌──────────────────┐
                                    │  duplicate_of │    │ outreach_queue   │
                                    │  (self-ref)   │    │ (1:1)            │
                                    └───────────────┘    └──────────────────┘

                                    ┌───────────────┐    ┌──────────────────┐
                                    │  crawl_runs   │    │ do_not_contact   │
                                    │ (pipeline log)│    │ (blocklist)      │
                                    └───────────────┘    └──────────────────┘
```

### Relationship Summary

| Parent | Child | Cardinality | FK |
|---|---|---|---|
| properties | property_sources | 1:N | property_sources.property_id |
| properties | property_contacts | 1:N | property_contacts.property_id |
| properties | property_media | 1:N | property_media.property_id |
| properties | property_changes | 1:N | property_changes.property_id |
| properties | outreach_queue | 1:1 | outreach_queue.property_id (UNIQUE) |
| properties | properties | 1:N (self) | properties.duplicate_of |
| query_bank | property_sources | 1:N | property_sources.query_id |
| users | outreach_queue | 1:N | outreach_queue.assigned_to |
| users | property_changes | 1:N | property_changes.changed_by |
| users | do_not_contact | 1:N | do_not_contact.added_by |
| crawl_runs | property_changes | 1:N | property_changes.crawl_run_id |

---

## 6. Index Strategy Summary

### High-Frequency Query Patterns

| Query Pattern | Table | Index Used |
|---|---|---|
| List properties by score, filter city/type/status | properties | `idx_properties_dashboard` |
| Find property by Google Place ID | properties | `idx_properties_google_place_id` |
| Geo-dedup: properties within 200m | properties | `idx_properties_location` (GIST) |
| Name-dedup: fuzzy match | properties | `idx_properties_normalized_name_trgm` (GIN) |
| Phone-dedup across properties | property_contacts | `idx_contacts_phone_dedup` |
| Load contacts for property | property_contacts | `idx_contacts_property` |
| Load media for property | property_media | `idx_media_property` |
| Find unscored properties | properties | `idx_properties_unscored` (partial) |
| Find un-briefed properties | properties | `idx_properties_unbriefed` (partial) |
| Outreach queue by assignee | outreach_queue | `idx_outreach_assigned_status` |
| Pipeline run history | crawl_runs | `idx_crawl_runs_started` |
| Do-not-contact check | do_not_contact | `idx_dnc_lookup` |

### Index Count Per Table

| Table | Indexes | Justification |
|---|---|---|
| properties | 9 | Central entity. Hit by dashboard, pipeline, and dedup. Every index maps to a known query. |
| property_contacts | 4 | Dedup queries on phone/email are critical path. |
| property_sources | 3 | Discovery dedup on external_id is hot path. |
| property_media | 2 | Read-heavy (dashboard), write-occasional (crawl). |
| outreach_queue | 3 | Outreach pipeline is a key workflow. |
| Others | 1-2 each | Low-volume tables, minimal indexing. |

---

## 7. Data Lifecycle & Retention

| Data | Retention | Cleanup Mechanism |
|---|---|---|
| properties | Permanent | Status changes only (never deleted) |
| property_sources | Permanent | Audit trail |
| property_contacts | Permanent | Soft-flagged, never deleted |
| property_media | 90 days (URL refs) / permanent (onboarded) | Weekly cleanup job removes stale media rows for rejected properties |
| property_changes | 6 months | Monthly purge of old change records |
| crawl_runs | 1 year | Monthly purge |
| Raw HTML snapshots (S3) | 90 days | S3 lifecycle policy |
| Redis dedup cache | Persistent (RDB backup) | Manual flush only |

---

## 8. Migration Strategy

### Tool
Alembic with async SQLAlchemy.

### Conventions
- One migration per logical change
- Migrations are forward-only in production (no downgrades)
- Naming: `XXXX_description.py` (e.g., `0001_initial_schema.py`)
- All migrations tested on a staging DB before production

### Initial Migration Order
```
0001_extensions.py          -- pgcrypto, postgis, pg_trgm
0002_users.py               -- users table
0003_sources.py             -- sources table
0004_query_bank.py          -- query_bank table
0005_properties.py          -- properties table (core)
0006_property_sources.py    -- property_sources table
0007_property_contacts.py   -- property_contacts table
0008_property_media.py      -- property_media table
0009_crawl_runs.py          -- crawl_runs table
0010_property_changes.py    -- property_changes table
0011_outreach_queue.py      -- outreach_queue table
0012_do_not_contact.py      -- do_not_contact table
0013_seed_sources.py        -- seed Phase 1 source records
```

---

## 9. Key Queries (Reference)

### Dashboard: Lead Queue
```sql
SELECT p.id, p.canonical_name, p.city, p.property_type, p.relevance_score,
       p.short_brief, p.status, p.canonical_phone, p.canonical_email
FROM properties p
WHERE p.city = :city
  AND p.property_type = ANY(:types)
  AND p.status = 'new'
  AND p.is_duplicate = false
ORDER BY p.relevance_score DESC
LIMIT 50 OFFSET :offset;
```

### Dedup: Geo + Name Similarity
```sql
SELECT p2.id, p2.canonical_name, p2.normalized_name,
       ST_Distance(p1.location, p2.location) AS distance_meters,
       similarity(p1.normalized_name, p2.normalized_name) AS name_similarity
FROM properties p1
JOIN properties p2
  ON p1.id != p2.id
  AND ST_DWithin(p1.location::geography, p2.location::geography, 500)
  AND similarity(p1.normalized_name, p2.normalized_name) > 0.3
WHERE p1.id = :property_id
  AND p2.is_duplicate = false;
```

### Pipeline: Properties Needing Scoring
```sql
SELECT p.id, p.property_type, p.city, p.features_json,
       (SELECT count(*) FROM property_contacts pc WHERE pc.property_id = p.id) AS contact_count
FROM properties p
WHERE p.scored_at IS NULL
  AND p.is_duplicate = false
ORDER BY p.created_at
LIMIT 100;
```

### Compliance: Do-Not-Contact Check
```sql
SELECT EXISTS (
    SELECT 1 FROM do_not_contact
    WHERE contact_type = :type
      AND contact_value = :normalized_value
) AS is_blocked;
```

---

*Next Step: API Contract Design → `/docs/api-spec.md`*

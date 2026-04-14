# FastRecce Platform — Backend Service Layer Design

> **Document Version:** 1.0
> **Date:** 2026-04-13
> **Status:** Draft — Pending Confirmation
> **Depends On:** [module-breakdown.md](./module-breakdown.md), [database-schema.md](./database-schema.md), [api-spec.md](./api-spec.md)

---

## 1. Service Layer Principles

| Principle | Application |
|---|---|
| **Services own all business logic** | Controllers validate input and call services. Services decide what to do. |
| **Services are framework-agnostic** | No FastAPI imports in services. They accept plain Python types and return plain Python types or Pydantic models. |
| **Services receive dependencies via constructor** | Database session, integration clients, and other services are injected — never imported globally. Makes testing trivial. |
| **Services never call controllers** | Data flows inward: Controller → Service → DB/Integration. Never the reverse. |
| **Services can call other services** | But only through explicit dependency injection. No circular dependencies. |
| **One service per module** | Each module (M1-M10) has exactly one service class as its public interface. |

---

## 2. Dependency Injection Pattern

All services follow the same constructor pattern:

```python
class ScoringService:
    def __init__(
        self,
        db: AsyncSession,
        llm_client: LLMClient,
    ):
        self.db = db
        self.llm_client = llm_client
```

FastAPI's dependency injection wires these up:

```python
# api/deps.py
async def get_scoring_service(
    db: AsyncSession = Depends(get_db),
    llm_client: LLMClient = Depends(get_llm_client),
) -> ScoringService:
    return ScoringService(db=db, llm_client=llm_client)
```

Pipeline tasks use the same services but construct them manually:

```python
# pipeline/tasks.py
async def score_properties_task():
    async with get_session() as db:
        service = ScoringService(db=db, llm_client=LLMClient())
        await service.score_batch()
```

**Same business logic, different entry points.** This is the key benefit of the service layer.

---

## 3. Service Catalog

### Dependency Graph

```
┌───────────────┐  ┌──────────────────┐
│ SourceService │  │ QueryBankService │
│     (M1)      │  │      (M2)        │
└───────┬───────┘  └────────┬─────────┘
        │                   │
        ▼                   ▼
┌──────────────────────────────────────┐
│         DiscoveryService (M3)        │
│  deps: GooglePlacesClient,           │
│        SourceService, QueryBankSvc   │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│         CrawlerService (M4)          │
│  deps: StorageClient, SourceService  │
│  contains: StructuredExtractor,      │
│            UnstructuredExtractor,     │
│            MediaExtractor            │
└───────┬──────────────┬───────────────┘
        │              │
        ▼              ▼
┌──────────────┐ ┌──────────────┐
│ContactService│ │ DedupService │
│    (M5)      │ │    (M6)      │
└──────┬───────┘ └──────┬───────┘
       │                │
       ▼                ▼
┌──────────────────────────────────────┐
│        PropertyService (core)        │
│  Canonical entity CRUD. Used by all. │
└──────────────────┬───────────────────┘
                   │
          ┌────────┼────────┐
          ▼                 ▼
┌──────────────┐   ┌───────────────┐
│ScoringService│   │BriefingService│
│    (M7)      │──▶│     (M8)      │
└──────┬───────┘   └───────┬───────┘
       │                   │
       ▼                   ▼
┌──────────────────────────────────────┐
│       OutreachService (M9)           │
└──────────────────────────────────────┘

┌──────────────────────────────────────┐
│       PipelineService (M10)          │
│  Orchestrates all of the above       │
└──────────────────────────────────────┘
```

---

## 4. Service Definitions

---

### 4.1 SourceService (M1)

**Module:** Source Registry
**File:** `app/services/source_service.py`
**Purpose:** CRUD for source configurations. Provides source rules to other services.

```python
class SourceService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_sources(
        self,
        source_type: str | None = None,
        is_enabled: bool | None = None,
    ) -> list[Source]:
        """List sources with optional filters."""

    async def get_source(self, source_id: UUID) -> Source:
        """Get a single source by ID. Raises NotFoundError."""

    async def get_source_by_name(self, source_name: str) -> Source:
        """Get source by name. Used by pipeline to look up crawl rules."""

    async def create_source(self, data: SourceCreate) -> Source:
        """Create a new source. Raises ConflictError if name exists."""

    async def update_source(self, source_id: UUID, data: SourceUpdate) -> Source:
        """Update source fields. Raises NotFoundError."""

    async def is_source_allowed(self, source_name: str) -> bool:
        """Check if source has access_policy='allowed' and is_enabled=true.
        Used by CrawlerService before crawling."""

    async def get_crawl_config(self, source_name: str) -> CrawlConfig:
        """Return crawl_method, rate_limit_rpm, parser_version for a source.
        Used by CrawlerService to determine how to crawl."""
```

**Business Rules:**
- Sources with `access_policy='restricted'` cannot be enabled for automated crawling. `is_source_allowed()` returns `false`.
- Deleting a source is not supported — only disable via `is_enabled=false`. Source history must be preserved.

**Dependencies:** None (foundational service).

---

### 4.2 QueryBankService (M2)

**Module:** Query Bank
**File:** `app/services/query_bank_service.py`
**Purpose:** Manage discovery queries. Track performance metrics per query.

```python
class QueryBankService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_queries(
        self,
        city: str | None = None,
        property_type: str | None = None,
        is_enabled: bool | None = None,
        sort_by: str = "quality_score_desc",
        cursor: str | None = None,
        page_size: int = 50,
    ) -> PaginatedResult[QueryBank]:
        """List queries with filters and pagination."""

    async def get_queries_for_discovery(
        self,
        cities: list[str] | None = None,
        property_types: list[str] | None = None,
    ) -> list[QueryBank]:
        """Get enabled queries for pipeline execution.
        Filters by city/type if provided, otherwise returns all enabled."""

    async def create_query(self, data: QueryCreate) -> QueryBank:
        """Create a new query. Raises ConflictError if (query_text, city) exists."""

    async def update_query(self, query_id: UUID, data: QueryUpdate) -> QueryBank:
        """Update query fields."""

    async def delete_query(self, query_id: UUID) -> None:
        """Hard delete a query. Raises NotFoundError."""

    async def record_run_result(
        self,
        query_id: UUID,
        results_count: int,
        new_properties_count: int,
    ) -> None:
        """Update run counters and quality_score after a discovery run.
        quality_score = new_properties / total_results (rolling)."""
```

**Business Rules:**
- `quality_score` is recomputed on every run: `new_properties / total_results`. A query that finds 0 new properties over 5 runs gets a very low quality score, signaling it should be reviewed or disabled.
- `UNIQUE(query_text, city)` enforced at DB level. Service raises `ConflictError`.

**Dependencies:** None.

---

### 4.3 DiscoveryService (M3)

**Module:** Discovery Engine
**File:** `app/services/discovery_service.py`
**Purpose:** Execute queries against Google Places API and produce candidate property records.

```python
class DiscoveryService:
    def __init__(
        self,
        db: AsyncSession,
        google_client: GooglePlacesClient,
        source_service: SourceService,
        query_bank_service: QueryBankService,
    ):
        self.db = db
        self.google_client = google_client
        self.source_service = source_service
        self.query_bank_service = query_bank_service

    async def discover(
        self,
        cities: list[str] | None = None,
        property_types: list[str] | None = None,
    ) -> list[DiscoveryCandidate]:
        """Run discovery for given cities/types.

        Steps:
        1. Fetch enabled queries from QueryBankService
        2. Check source is allowed via SourceService
        3. For each query, call Google Places Text Search
        4. For each result, call Google Places Details
        5. Filter out already-known place_ids
        6. Record run stats per query
        7. Return list of DiscoveryCandidate objects
        """

    async def _search_google_places(
        self,
        query: QueryBank,
    ) -> list[GooglePlaceResult]:
        """Execute a single Google Places text search query.
        Handles pagination (nextPageToken) up to 3 pages (60 results)."""

    async def _fetch_place_details(
        self,
        place_id: str,
    ) -> GooglePlaceDetails:
        """Fetch detailed info for a place_id.
        Returns: name, address, phone, website, rating, reviews, lat/lng, types."""

    async def _is_known_place(self, google_place_id: str) -> bool:
        """Check if place_id already exists in property_sources.
        Uses Redis cache first, falls back to DB query."""

    async def _to_candidate(
        self,
        details: GooglePlaceDetails,
        query: QueryBank,
    ) -> DiscoveryCandidate:
        """Map Google Places result to internal candidate model."""
```

**Data Types:**

```python
@dataclass
class DiscoveryCandidate:
    """Output of discovery — input to crawl pipeline."""
    google_place_id: str
    name: str
    address: str
    city: str
    locality: str | None
    lat: float
    lng: float
    phone: str | None
    website: str | None
    google_rating: float | None
    google_review_count: int | None
    google_types: list[str]
    property_type: str          # Inferred from query + google types
    source_query_id: UUID
    raw_result: dict            # Full API response for archival
```

**Business Rules:**
- Only execute queries where the associated source (`google_places`) is enabled and allowed.
- Deduplicate within a single run: if two queries return the same `place_id`, process it only once.
- Use Redis set `known_place_ids` as a fast filter. Rebuild from DB on cache miss.
- Respect rate limits: `rate_limit_rpm` from SourceService. Use `asyncio.Semaphore` + sleep.
- Record per-query stats via `QueryBankService.record_run_result()`.

**Dependencies:** SourceService, QueryBankService, GooglePlacesClient.

---

### 4.4 CrawlerService (M4)

**Module:** Crawl & Extraction Engine
**File:** `app/services/crawler_service.py`
**Purpose:** Crawl property websites and extract structured/unstructured data.

```python
class CrawlerService:
    def __init__(
        self,
        db: AsyncSession,
        source_service: SourceService,
        storage_client: StorageClient,
        structured_extractor: StructuredExtractor,
        unstructured_extractor: UnstructuredExtractor,
        media_extractor: MediaExtractor,
    ):
        self.db = db
        self.source_service = source_service
        self.storage_client = storage_client
        self.structured_extractor = structured_extractor
        self.unstructured_extractor = unstructured_extractor
        self.media_extractor = media_extractor

    async def crawl_property(
        self,
        candidate: DiscoveryCandidate,
    ) -> CrawlResult:
        """Full crawl pipeline for a single property.

        Steps:
        1. Check if website exists. If not, return API-only result.
        2. Determine crawl_method from SourceService.
        3. Fetch target pages (home, contact, about, footer).
        4. Compute snapshot hash. Skip if unchanged from last crawl.
        5. Run structured extractor (schema.org, JSON-LD, tel/mailto).
        6. Run unstructured extractor (free text, amenities, descriptions).
        7. Run media extractor (images, alt text, perceptual hashes).
        8. Archive raw HTML to S3.
        9. Return aggregated CrawlResult.
        """

    async def crawl_batch(
        self,
        candidates: list[DiscoveryCandidate],
        concurrency: int = 5,
    ) -> list[CrawlResult]:
        """Crawl multiple properties with controlled concurrency.
        Uses asyncio.Semaphore to limit concurrent HTTP connections."""

    async def _fetch_pages(
        self,
        website_url: str,
        crawl_method: str,
    ) -> list[FetchedPage]:
        """Fetch target pages from a property website.

        Target pages discovered by:
        1. Start with homepage
        2. Find links matching: /contact, /about, /venue, /events, /rooms
        3. Extract footer section from homepage
        4. Max 6 pages per property (prevent runaway crawls)
        """

    async def _should_skip(
        self,
        website_url: str,
        content_hash: str,
    ) -> bool:
        """Check raw_snapshot_hash in property_sources.
        If unchanged, skip extraction (content hasn't changed)."""

    async def _check_robots_txt(self, domain: str) -> RobotsRules:
        """Fetch and parse robots.txt. Cache per domain in Redis (24h TTL).
        Respect disallowed paths."""
```

**Sub-components (Extractors):**

```python
# app/services/extractors/structured.py
class StructuredExtractor:
    """Extracts data from structured markup in HTML."""

    def extract(self, pages: list[FetchedPage]) -> StructuredData:
        """Extract from:
        - schema.org / JSON-LD blocks
        - <a href="tel:..."> links
        - <a href="mailto:..."> links
        - <a href="https://wa.me/..."> links
        - <address> blocks
        - <meta> tags (description, og:title, og:image)
        Returns: phones, emails, whatsapp_links, addresses, schema_data
        """

# app/services/extractors/unstructured.py
class UnstructuredExtractor:
    """Extracts data from free text content."""

    def extract(self, pages: list[FetchedPage]) -> UnstructuredData:
        """Extract from:
        - About section text → property description
        - Amenity lists → feature tags
        - FAQ sections → additional context
        - Page titles and headings → property type cues
        - Captions → visual descriptors
        Uses regex patterns for phone/email in body text (lower confidence).
        Returns: description, amenities, feature_tags, text_contacts
        """

# app/services/extractors/media.py
class MediaExtractor:
    """Extracts and processes media from HTML pages."""

    def extract(self, pages: list[FetchedPage]) -> list[MediaItem]:
        """Extract from:
        - <img> tags with src and alt text
        - og:image meta tags
        - Background images in inline styles
        Compute perceptual hash (dHash) for each image.
        Filter out tiny images (<200px), icons, logos.
        Returns: list of MediaItem(url, alt_text, hash, width, height)
        """
```

**Data Types:**

```python
@dataclass
class FetchedPage:
    url: str
    page_type: str              # 'home', 'contact', 'about', 'venue', 'footer'
    status_code: int
    html: str
    content_hash: str           # SHA-256 of HTML content
    fetched_at: datetime

@dataclass
class CrawlResult:
    candidate: DiscoveryCandidate
    pages_fetched: int
    structured_data: StructuredData
    unstructured_data: UnstructuredData
    media_items: list[MediaItem]
    snapshot_hash: str           # Hash of all page hashes combined
    snapshot_paths: list[str]    # S3 paths for archived HTML
    crawl_status: str            # 'completed', 'partial', 'failed'
    errors: list[str]

@dataclass
class StructuredData:
    phones: list[ExtractedContact]
    emails: list[ExtractedContact]
    whatsapp_links: list[ExtractedContact]
    addresses: list[str]
    schema_org_data: dict | None
    meta_description: str | None

@dataclass
class UnstructuredData:
    description: str | None
    amenities: list[str]
    feature_tags: list[str]     # ['lawn', 'pool', 'heritage', 'rustic']
    text_contacts: list[ExtractedContact]  # Lower confidence contacts

@dataclass
class ExtractedContact:
    contact_type: str           # 'phone', 'email', 'whatsapp', 'form'
    value: str
    source_url: str             # Which page it was found on
    extraction_method: str      # 'tel_link', 'mailto_link', 'schema_org', 'text_regex'
    confidence: float           # 0.0 to 1.0
```

**Business Rules:**
- Max 6 pages crawled per property. Prevents runaway crawls on large sites.
- 30-second timeout per page fetch. Fail gracefully on timeout.
- Respect `robots.txt`. Skip disallowed paths.
- Max 2 concurrent requests per domain. 1-second delay between requests to the same domain.
- Use `httpx` by default. Fall back to Playwright only if `crawl_method='browser_render'` or if initial fetch returns empty body (JS-rendered page).
- Snapshot hash comparison: if hash matches previous crawl, skip extraction entirely. This is the primary efficiency mechanism for daily re-crawls.

**Dependencies:** SourceService, StorageClient, Extractors (internal).

---

### 4.5 ContactService (M5)

**Module:** Contact Resolution
**File:** `app/services/contact_service.py`
**Purpose:** Merge, validate, and persist contacts from multiple extraction sources. Enforce compliance rules.

```python
class ContactService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def resolve_contacts(
        self,
        property_id: UUID,
        api_contacts: list[ExtractedContact],
        crawl_contacts: list[ExtractedContact],
    ) -> list[PropertyContact]:
        """Merge contacts from API and crawl into canonical contact records.

        Steps:
        1. Normalize all contact values (strip formatting, lowercase emails).
        2. Deduplicate by (contact_type, normalized_value).
        3. Apply precedence rules to pick confidence scores.
        4. Check against do_not_contact list.
        5. Flag personal-looking contacts.
        6. Upsert into property_contacts table.
        7. Select best phone/email as canonical contacts on property.
        8. Return resolved contacts.
        """

    async def get_contacts_for_property(
        self, property_id: UUID
    ) -> list[PropertyContact]:
        """Retrieve all contacts for a property, ordered by confidence DESC."""

    async def check_do_not_contact(
        self,
        contact_type: str,
        contact_value: str,
    ) -> bool:
        """Check if a contact is on the blocklist. Returns True if blocked."""

    async def add_to_do_not_contact(
        self,
        contact_type: str,
        contact_value: str,
        reason: str,
        added_by: UUID,
    ) -> None:
        """Add a contact to the do-not-contact list."""

    async def compute_contact_completeness(
        self, property_id: UUID
    ) -> float:
        """Compute contact completeness score (0-1) for scoring engine.
        phone + email + website = 1.0
        phone + email = 0.8
        phone only = 0.5
        email only = 0.4
        form/whatsapp only = 0.3
        no contacts = 0.0
        """

    # --- Private methods ---

    def _normalize_phone(self, phone: str) -> str:
        """Strip spaces, dashes, parens. Add country code if missing.
        '+91 98765 43210' → '919876543210'
        '098765 43210' → '919876543210'
        """

    def _normalize_email(self, email: str) -> str:
        """Lowercase, strip whitespace.
        ' Info@SunsetVilla.com ' → 'info@sunsetvilla.com'
        """

    def _is_personal_contact(self, contact_type: str, value: str) -> bool:
        """Heuristic: flag contacts that look personal, not business.
        Email: gmail.com, yahoo.com, hotmail.com, outlook.com → flagged
        Phone: cannot reliably determine (all Indian mobiles look the same)
        Returns True if likely personal.
        """

    def _assign_confidence(self, contact: ExtractedContact) -> float:
        """Confidence based on extraction method:
        api_structured     → 0.95
        tel_link           → 0.90
        mailto_link        → 0.90
        schema_org         → 0.85
        whatsapp_link      → 0.80
        text_regex_phone   → 0.60
        text_regex_email   → 0.55
        contact_form       → 0.50
        instagram          → 0.30
        """

    async def _select_canonical_contacts(self, property_id: UUID) -> None:
        """Pick the best phone and email from property_contacts
        and write them to properties.canonical_phone/email.
        Selection: highest confidence, prefer is_public_business_contact=true.
        """
```

**Business Rules:**
- **Precedence order** (from PRD): API phone > page phone > mailto > text email > forms > WhatsApp > Instagram.
- **Personal contact detection**: Gmail/Yahoo/Hotmail emails are flagged `flagged_personal=true`. They are stored but not auto-approved for outreach.
- **Do-not-contact check** runs on every contact upsert. Blocked contacts are silently dropped.
- **Canonical contact selection** runs after every contact resolution. Updates `properties.canonical_phone` and `properties.canonical_email` with the highest-confidence business contact.
- **Upsert logic**: `ON CONFLICT (property_id, contact_type, normalized_value) DO UPDATE SET last_seen_at, confidence` — contacts are updated, not duplicated.

**Dependencies:** None (reads/writes directly to DB).

---

### 4.6 DedupService (M6)

**Module:** Deduplication Engine
**File:** `app/services/dedup_service.py`
**Purpose:** Detect and resolve duplicate properties using multi-signal matching.

```python
class DedupService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_duplicates(
        self,
        candidate: DiscoveryCandidate,
    ) -> DedupResult:
        """Check if a candidate is a duplicate of an existing property.

        Runs matching signals in order of cost (cheapest first):
        1. Google Place ID exact match → definite duplicate
        2. Phone number match → high signal
        3. Website domain match → high signal
        4. Geo proximity (< 200m) + name similarity (> 0.5) → probable duplicate
        5. Image hash match → supporting signal

        Returns DedupResult with match status and candidate list.
        """

    async def find_duplicates_for_property(
        self, property_id: UUID
    ) -> list[DuplicateCandidate]:
        """Find potential duplicates for an existing property.
        Used by GET /properties/:id/duplicates endpoint.
        Runs full matching pipeline and returns scored candidates."""

    async def merge_properties(
        self,
        source_id: UUID,
        target_id: UUID,
        merged_by: UUID,
    ) -> Property:
        """Merge source property into target (canonical) property.

        Steps:
        1. Move all property_sources from source → target
        2. Merge property_contacts (dedup by normalized_value)
        3. Merge property_media (dedup by image_hash)
        4. Mark source as is_duplicate=true, duplicate_of=target
        5. Set source status to 'reviewed'
        6. Recalculate target's canonical contacts
        7. Log change in property_changes
        8. Return updated target property
        """

    async def run_batch_dedup(self) -> BatchDedupResult:
        """Weekly batch dedup pass.
        Compares all non-duplicate properties against each other.
        Uses geo-clustering to reduce comparison space:
        1. Group properties by city
        2. Within city, cluster by locality/geo proximity
        3. Within cluster, run full matching signals
        Returns list of potential duplicates for human review.
        """

    async def filter_known_candidates(
        self,
        candidates: list[DiscoveryCandidate],
    ) -> list[DiscoveryCandidate]:
        """Fast filter: remove candidates whose google_place_id
        already exists in property_sources. Used during discovery stage.
        Checks Redis cache first, then DB."""

    # --- Private methods ---

    async def _match_by_place_id(self, place_id: str) -> Property | None:
        """Exact match on google_place_id. Definite duplicate."""

    async def _match_by_phone(self, phone: str) -> list[Property]:
        """Find properties sharing a phone number.
        Uses property_contacts.normalized_value index."""

    async def _match_by_website(self, website: str) -> list[Property]:
        """Find properties sharing a website domain.
        Normalize: strip www, protocol, trailing slash."""

    async def _match_by_geo_name(
        self, lat: float, lng: float, name: str
    ) -> list[tuple[Property, float, float]]:
        """Find properties within 500m with name similarity > 0.3.
        Uses PostGIS ST_DWithin + pg_trgm similarity().
        Returns: [(property, distance_meters, name_similarity)]"""

    def _compute_duplicate_confidence(
        self,
        signals: dict[str, Any],
    ) -> float:
        """Weighted confidence from matching signals:
        place_id_match  → 1.0 (definite)
        phone_match     → 0.85
        website_match   → 0.80
        geo_close + name_similar → 0.3 + (name_similarity * 0.5)
        image_hash_match → +0.15 (additive)
        Maximum: 1.0
        """
```

**Data Types:**

```python
@dataclass
class DedupResult:
    is_duplicate: bool
    confidence: float
    matched_property_id: UUID | None    # If definite match
    candidates: list[DuplicateCandidate]  # If uncertain

@dataclass
class DuplicateCandidate:
    property_id: UUID
    canonical_name: str
    city: str
    duplicate_confidence: float
    match_signals: dict  # {name_similarity, distance_meters, phone_match, website_match}

@dataclass
class BatchDedupResult:
    pairs_checked: int
    auto_merged: int              # High-confidence auto-merges
    flagged_for_review: int       # Medium-confidence, needs human
    duration_seconds: float
```

**Business Rules:**
- **Auto-merge threshold:** `confidence >= 0.90` (same place_id, or phone+website+geo all match). No human needed.
- **Review threshold:** `0.50 <= confidence < 0.90`. Surfaced as duplicate warning on dashboard.
- **No match:** `confidence < 0.50`. Treated as distinct property.
- **Merge is one-directional:** Source → Target. The target keeps its `id`. Source gets `is_duplicate=true`.
- **Batch dedup** uses geo-clustering to avoid O(n^2) comparisons. Properties >50km apart are never compared.

**Dependencies:** None (direct DB access with PostGIS and pg_trgm queries).

---

### 4.7 PropertyService (Core)

**Module:** Cross-cutting — used by most other services and all API endpoints
**File:** `app/services/property_service.py`
**Purpose:** CRUD for canonical property entities. The central data access service.

```python
class PropertyService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- Read operations (Dashboard API) ---

    async def list_properties(
        self,
        filters: PropertyFilters,
        sort: str = "relevance_score_desc",
        cursor: str | None = None,
        page_size: int = 50,
    ) -> PaginatedResult[PropertySummary]:
        """List properties with filters and cursor pagination.
        Returns summary projections (not full entity)."""

    async def get_property(self, property_id: UUID) -> PropertyDetail:
        """Full property detail with related data.
        Eagerly loads: sources, contacts, media, outreach.
        Single DB query with JOINs."""

    async def get_property_changes(
        self,
        property_id: UUID,
        cursor: str | None = None,
        page_size: int = 20,
    ) -> PaginatedResult[PropertyChange]:
        """Change history for a property."""

    async def search_properties(self, query: str) -> list[PropertySummary]:
        """Full-text search on canonical_name, locality.
        Uses pg_trgm for fuzzy matching."""

    # --- Write operations (Pipeline) ---

    async def upsert_from_discovery(
        self,
        candidate: DiscoveryCandidate,
        crawl_result: CrawlResult | None,
        contacts: list[PropertyContact],
        dedup_result: DedupResult,
    ) -> Property:
        """Create or update a property from pipeline data.

        If dedup says it's a known property → update existing.
        If dedup says it's new → create new.
        If dedup is uncertain → create new + flag duplicate warning.

        Steps:
        1. Determine property_type from candidate + Google types
        2. Create/update property record
        3. Create property_source linking record
        4. Store contacts via ContactService
        5. Store media items
        6. Log 'created' or relevant change_type
        7. Return property
        """

    async def get_unscored(self, limit: int = 100) -> list[Property]:
        """Properties where scored_at IS NULL. For scoring pipeline."""

    async def get_unbriefed(self, limit: int = 100) -> list[Property]:
        """Properties where brief_generated_at IS NULL and scored_at IS NOT NULL.
        For briefing pipeline."""

    # --- Write operations (Dashboard) ---

    async def review_property(
        self,
        property_id: UUID,
        action: str,
        reviewer_id: UUID,
        notes: str | None = None,
        merge_into_id: UUID | None = None,
    ) -> Property:
        """Execute a review action on a property.

        Validates status transitions:
        - approve: new → approved. Creates outreach queue entry.
        - reject: new → rejected.
        - do_not_contact: any → do_not_contact. Blocklists contacts.
        - merge: delegates to DedupService.merge_properties().
        - reopen: rejected → new.

        Logs change in property_changes.
        Raises ConflictError on invalid transitions.
        """

    async def manual_import(
        self,
        data: ManualImportData,
        imported_by: UUID,
    ) -> Property:
        """Create a property from manual import (restricted sources).
        Does NOT trigger crawl for restricted sources.
        Marks source as 'manual'."""

    async def update_score(
        self,
        property_id: UUID,
        score: float,
        score_reason: dict,
    ) -> None:
        """Update relevance_score and score_reason_json.
        Called by ScoringService."""

    async def update_brief(
        self,
        property_id: UUID,
        brief: str,
    ) -> None:
        """Update short_brief and brief_generated_at.
        Called by BriefingService."""

    # --- Helpers ---

    def _infer_property_type(
        self,
        query_property_type: str,
        google_types: list[str],
    ) -> str:
        """Map Google Places types to FastRecce property types.
        Google type 'lodging' + query type 'villa' → 'villa'
        Google type 'restaurant' → 'restaurant'
        Google type 'school' → 'school_campus'
        Falls back to query's property_type if Google types are ambiguous.
        """

    def _normalize_name(self, name: str) -> str:
        """Lowercase, strip punctuation, collapse whitespace.
        'The Oberoi, Mumbai' → 'oberoi mumbai'
        Used for dedup matching.
        """
```

**Business Rules:**
- **Upsert idempotency:** If the same `google_place_id` is discovered again, updates the existing property (via DedupService match), doesn't create a new one.
- **Status transitions are enforced:** See table in API spec. Invalid transitions raise `ConflictError`.
- **Manual import** does not crawl the source URL if source `access_policy='restricted'`. The analyst provides data manually.

**Dependencies:** ContactService (for canonical contact selection), DedupService (for merge operations).

---

### 4.8 ScoringService (M7)

**Module:** Relevance Scoring Engine
**File:** `app/services/scoring_service.py`
**Purpose:** Score properties on shoot-relevance using weighted formula.

```python
class ScoringService:
    def __init__(
        self,
        db: AsyncSession,
        llm_client: LLMClient,
    ):
        self.db = db
        self.llm_client = llm_client

    async def score_property(self, property_id: UUID) -> ScoringResult:
        """Score a single property. Used for manual re-scoring.

        Loads property + contacts + media, computes all sub-scores,
        applies weighted formula, stores result.
        """

    async def score_batch(self, limit: int = 100) -> BatchScoringResult:
        """Score all unscored properties. Daily pipeline entry point.

        Steps:
        1. Fetch unscored properties
        2. For each, compute all sub-scores
        3. Apply weighted formula
        4. Store score + score_reason_json
        5. Return batch result
        """

    # --- Sub-score computers ---

    def _score_type_fit(self, property_type: str) -> float:
        """How well the property type fits shoot use-cases.
        villa=0.9, resort=0.9, heritage_home=0.95, warehouse=0.85,
        farmhouse=0.85, bungalow=0.9, theatre_studio=0.95,
        cafe=0.6, restaurant=0.5, office_space=0.4, other=0.3
        """

    async def _score_shoot_fit(
        self, features: dict, description: str | None
    ) -> float:
        """How suitable for shoots based on feature signals.
        Uses keyword matching + LLM assessment.
        Positive signals: 'events', 'shoots', 'photoshoot', 'film-friendly',
        'large rooms', 'lawn', 'terrace', 'industrial look', 'rustic'.
        Returns 0.0-1.0.
        """

    async def _score_visual_uniqueness(
        self, features: dict, property_type: str, description: str | None
    ) -> float:
        """How visually distinctive the property is.
        LLM-assessed based on description + features.
        Generic apartment listing = 0.1, heritage mansion = 0.9.
        """

    def _score_location_demand(self, city: str, locality: str | None) -> float:
        """How in-demand the city is for shoots.
        Mumbai=0.95, Pune=0.8, Lonavala=0.85, Alibaug=0.9,
        Thane=0.7, Navi Mumbai=0.6.
        Configurable weights, not hardcoded for scale.
        """

    def _score_contact_completeness(
        self, contact_completeness: float
    ) -> float:
        """Direct pass-through from ContactService.compute_contact_completeness()."""

    def _score_website_quality(self, website: str | None, features: dict) -> float:
        """Website exists and looks professional.
        No website = 0.0
        Has website = 0.5
        Has website + schema markup = 0.7
        Has website + venue/events page = 0.9
        """

    def _score_activity_recency(
        self, google_review_count: int | None, last_seen_at: datetime | None
    ) -> float:
        """Is the property still active?
        >100 Google reviews + recent crawl = 0.9
        >10 reviews = 0.6
        No reviews = 0.3
        Not seen in 30+ days = 0.1
        """

    def _score_ease_of_outreach(self, contacts: list[PropertyContact]) -> float:
        """How easy is it to reach the property?
        Has WhatsApp = 0.9
        Has direct phone + email = 0.8
        Has contact form = 0.5
        Only Instagram = 0.2
        No contact = 0.0
        """

    def _compute_weighted_score(self, sub_scores: dict[str, float]) -> float:
        """Apply PRD formula:
        0.20*type_fit + 0.20*shoot_fit + 0.15*visual_uniqueness +
        0.10*location_demand + 0.10*contact_completeness +
        0.10*website_quality + 0.10*activity_recency + 0.05*ease_of_outreach
        """
```

**Data Types:**

```python
@dataclass
class ScoringResult:
    property_id: UUID
    relevance_score: float          # 0.0 to 1.0
    sub_scores: dict[str, float]    # Individual factor scores
    scored_at: datetime

@dataclass
class BatchScoringResult:
    scored_count: int
    failed_count: int
    avg_score: float
    duration_seconds: float
```

**Business Rules:**
- **LLM calls** are used only for `shoot_fit` and `visual_uniqueness` — the two subjective factors. All other sub-scores are deterministic.
- **LLM failure fallback:** If Gemini API is down, use keyword-matching heuristic for `shoot_fit` and default `visual_uniqueness=0.5`. Flag property as `needs_rescore`.
- **Score weights are configurable** — stored in a config file, not hardcoded. Monthly recalibration updates weights based on reviewer accept/reject patterns.
- **Batch scoring** processes 100 properties at a time. LLM calls are batched to minimize API round-trips.

**Dependencies:** LLMClient, ContactService (for contact_completeness).

---

### 4.9 BriefingService (M8)

**Module:** AI Brief Generator
**File:** `app/services/briefing_service.py`
**Purpose:** Generate operational property briefs using LLM.

```python
class BriefingService:
    def __init__(
        self,
        db: AsyncSession,
        llm_client: LLMClient,
    ):
        self.db = db
        self.llm_client = llm_client

    async def generate_brief(self, property_id: UUID) -> str:
        """Generate brief for a single property.

        Steps:
        1. Load property with features, contacts, scores
        2. Build prompt with property context
        3. Call LLM
        4. Validate output (2-3 sentences, operational tone)
        5. Store in properties.short_brief
        6. Return brief text
        """

    async def generate_batch(self, limit: int = 100) -> int:
        """Generate briefs for all un-briefed properties.
        Returns count of briefs generated."""

    async def regenerate_brief(self, property_id: UUID) -> str:
        """Force regeneration of brief (user-triggered).
        Ignores brief_generated_at check."""

    def _build_prompt(self, property: Property, contacts: list, scores: dict) -> str:
        """Build LLM prompt for brief generation.

        System prompt (cacheable):
        'You are an internal analyst at FastRecce, a location scouting platform
         for film and ad shoots. Generate a 2-3 sentence operational brief...'

        User prompt:
        'Property: {name}, {city}, {type}
         Features: {features}
         Score: {score} (top factors: {top_factors})
         Contacts available: {contact_types}
         Generate a brief for internal reviewers.'
        """

    def _fallback_brief(self, property: Property) -> str:
        """Template-based fallback when LLM is unavailable.
        '{property_type} in {city}/{locality}. {amenity_count} amenities listed.
         Contact available via {contact_types}. Relevance score: {score}.'
        """
```

**Business Rules:**
- **Brief tone:** Operational, not marketing. "Strong fit for..." not "Stunning property!"
- **Brief length:** 2-3 sentences. LLM output is validated — if too long, truncated.
- **Cache:** Brief is only regenerated when property data changes (scored_at > brief_generated_at) or when manually triggered.
- **Context caching:** System prompt is the same for all properties — uses Gemini API context caching to reduce cost.
- **Fallback:** Template-based brief if LLM fails. Property is flagged for LLM retry in next run.

**Dependencies:** LLMClient.

---

### 4.10 OutreachService (M9)

**Module:** Outreach Pipeline
**File:** `app/services/outreach_service.py`
**Purpose:** Manage the outreach queue and workflow.

```python
class OutreachService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_outreach(
        self,
        filters: OutreachFilters,
        sort: str = "priority_desc",
        cursor: str | None = None,
        page_size: int = 50,
    ) -> PaginatedResult[OutreachItem]:
        """List outreach queue with filters. Joins property summary."""

    async def get_outreach_stats(
        self,
        city: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> OutreachStats:
        """Compute funnel statistics."""

    async def create_outreach_entry(
        self,
        property_id: UUID,
        priority: int | None = None,
    ) -> OutreachQueue:
        """Create outreach entry when property is approved.
        Priority defaults to relevance_score * 100.
        Generates suggested outreach angle via LLM (async, non-blocking)."""

    async def update_outreach(
        self,
        outreach_id: UUID,
        data: OutreachUpdate,
        updated_by: UUID,
    ) -> OutreachQueue:
        """Update outreach status, assignment, notes.
        Validates status transitions. Checks do_not_contact before status change.
        Increments contact_attempts on status='contacted'.
        """

    def _validate_status_transition(self, current: str, target: str) -> bool:
        """Check if status transition is valid per the transition matrix."""

    VALID_TRANSITIONS: dict[str, list[str]] = {
        "pending": ["contacted", "declined"],
        "contacted": ["responded", "follow_up", "no_response", "declined"],
        "responded": ["follow_up", "converted", "declined"],
        "follow_up": ["contacted", "converted", "declined", "no_response"],
        "no_response": ["contacted", "follow_up", "declined"],
    }
```

**Business Rules:**
- **Priority** defaults to `round(relevance_score * 100)`. Can be overridden by reviewer.
- **Contact attempt tracking:** Every `status='contacted'` transition increments `contact_attempts` and sets `last_contact_at`.
- **Do-not-contact enforcement:** Before any outreach status change, check if the property's contacts are blocklisted. Return `422 UNPROCESSABLE` if blocked.
- **Follow-up reminders:** When `follow_up_at` is set, the dashboard can query for due follow-ups.

**Dependencies:** ContactService (for DNC check).

---

### 4.11 PipelineService (M10)

**Module:** Pipeline Orchestrator
**File:** `app/services/pipeline_service.py`
**Purpose:** Orchestrate pipeline stages, manage crawl runs, provide health status.

```python
class PipelineService:
    def __init__(
        self,
        db: AsyncSession,
        discovery_service: DiscoveryService,
        crawler_service: CrawlerService,
        contact_service: ContactService,
        dedup_service: DedupService,
        property_service: PropertyService,
        scoring_service: ScoringService,
        briefing_service: BriefingService,
    ):
        # All services injected
        ...

    async def run_daily_pipeline(
        self,
        cities: list[str] | None = None,
        property_types: list[str] | None = None,
    ) -> CrawlRun:
        """Execute the full daily pipeline.

        Steps:
        1. Create crawl_run record (status='running')
        2. Discovery: find candidates
        3. Filter known: remove already-seen place_ids
        4. Crawl: fetch websites for new candidates
        5. Contacts: resolve contacts for each
        6. Dedup: check for duplicates
        7. Upsert: create/update properties
        8. Score: score unscored properties
        9. Brief: generate briefs for un-briefed properties
        10. Update crawl_run record (status='completed', counters)
        11. Return crawl_run

        Each step catches its own exceptions.
        Pipeline continues even if individual properties fail.
        Errors are collected in crawl_run.errors_json.
        """

    async def run_weekly_enrichment(self) -> CrawlRun:
        """Weekly deep enrichment.
        1. Re-crawl high-priority properties (score > 0.7)
        2. Run batch dedup
        3. Dead-link cleanup (check properties not seen in 30+ days)
        4. Re-score all properties
        5. Export weekly report
        """

    async def trigger_manual_run(
        self,
        run_type: str,
        cities: list[str] | None = None,
        property_types: list[str] | None = None,
    ) -> CrawlRun:
        """API-triggered pipeline run. Creates crawl_run and dispatches to task queue."""

    async def get_pipeline_health(self) -> PipelineHealth:
        """Aggregate health stats for dashboard."""

    async def list_runs(
        self,
        run_type: str | None = None,
        status: str | None = None,
        cursor: str | None = None,
        page_size: int = 20,
    ) -> PaginatedResult[CrawlRun]:
        """List crawl runs with filters."""
```

**Daily Pipeline Flow (Pseudocode):**

```python
async def run_daily_pipeline(self, cities, property_types):
    run = await self._create_run("daily")

    try:
        # Stage 1: Discover
        candidates = await self.discovery_service.discover(cities, property_types)
        run.queries_executed = len(queries_used)

        # Stage 2: Filter known
        new_candidates = await self.dedup_service.filter_known_candidates(candidates)
        run.skipped_duplicates = len(candidates) - len(new_candidates)

        # Stage 3-6: Process each candidate
        for candidate in new_candidates:
            try:
                # Crawl
                crawl_result = await self.crawler_service.crawl_property(candidate)

                # Resolve contacts
                api_contacts = self._extract_api_contacts(candidate)
                crawl_contacts = (crawl_result.structured_data.phones +
                                  crawl_result.structured_data.emails + ...)
                contacts = await self.contact_service.resolve_contacts(
                    property_id=None,  # Not yet created
                    api_contacts=api_contacts,
                    crawl_contacts=crawl_contacts,
                )

                # Dedup check
                dedup_result = await self.dedup_service.check_duplicates(candidate)

                # Upsert
                property = await self.property_service.upsert_from_discovery(
                    candidate, crawl_result, contacts, dedup_result
                )

                if dedup_result.is_duplicate:
                    run.skipped_duplicates += 1
                else:
                    run.new_properties += 1

                run.urls_processed += 1

            except Exception as e:
                run.crawl_errors += 1
                run.errors_json.append({
                    "candidate": candidate.name,
                    "error": str(e),
                    "stage": "process",
                })
                continue  # Don't fail the whole pipeline

        # Stage 7: Score unscored
        score_result = await self.scoring_service.score_batch()

        # Stage 8: Brief un-briefed
        brief_count = await self.briefing_service.generate_batch()

        # Finalize
        run.status = "completed"
        run.finished_at = utcnow()
        run.duration_seconds = (run.finished_at - run.started_at).seconds

    except Exception as e:
        run.status = "failed"
        run.errors_json.append({"error": str(e), "stage": "pipeline"})

    await self._save_run(run)
    return run
```

**Business Rules:**
- **Individual failures don't kill the pipeline.** Each candidate is processed in a try/except. Errors are logged in `crawl_run.errors_json`.
- **Stages are sequential within the daily run** but batch operations (scoring, briefing) process multiple properties.
- **Idempotent:** Running the same pipeline twice on the same day produces the same result (dedup filter removes already-seen candidates, snapshot hash skips unchanged content).

**Dependencies:** All pipeline services (M3-M8).

---

## 5. Integration Clients

---

### 5.1 GooglePlacesClient

**File:** `app/integrations/google_places.py`

```python
class GooglePlacesClient:
    def __init__(self, api_key: str, rate_limit_rpm: int = 60):
        self.api_key = api_key
        self.rate_limiter = RateLimiter(max_rpm=rate_limit_rpm)
        self.http = httpx.AsyncClient(timeout=30)

    async def text_search(
        self,
        query: str,
        location_bias: dict | None = None,
    ) -> list[PlaceSearchResult]:
        """Google Places Text Search (New) API.
        Handles nextPageToken pagination (max 3 pages = 60 results).
        """

    async def get_place_details(
        self,
        place_id: str,
        fields: list[str] | None = None,
    ) -> PlaceDetails:
        """Google Places Details (New) API.
        Default fields: displayName, formattedAddress, nationalPhoneNumber,
        websiteUri, rating, userRatingCount, location, types, googleMapsUri.
        """

    async def close(self):
        await self.http.aclose()
```

**Notes:**
- Uses Google Places API (New) — the modern version with field-mask based pricing.
- Rate limiter uses Redis token bucket shared across pipeline workers.
- API key stored in environment variable, never logged or stored in DB.

---

### 5.2 LLMClient

**File:** `app/integrations/llm.py`

```python
from google import genai

class LLMClient:
    def __init__(self, api_key: str, model: str = "gemini-3-flash"):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    async def generate_brief(
        self,
        system_prompt: str,
        property_context: str,
    ) -> str:
        """Generate property brief.
        Uses context caching for system_prompt (same across all calls).
        max_output_tokens: 200. temperature: 0.3 (factual, not creative).
        """

    async def assess_shoot_fit(
        self,
        property_description: str,
        features: list[str],
    ) -> float:
        """LLM-assessed shoot fit score.
        Returns 0.0-1.0 via structured output (response_schema with JSON mode).
        """

    async def assess_visual_uniqueness(
        self,
        property_type: str,
        description: str,
        features: list[str],
    ) -> float:
        """LLM-assessed visual uniqueness score.
        Returns 0.0-1.0 via structured output (response_schema with JSON mode).
        """

    async def generate_outreach_angle(
        self,
        property_brief: str,
        property_type: str,
    ) -> str:
        """Generate suggested outreach angle for sales team.
        max_output_tokens: 100.
        """
```

**Notes:**
- Uses `gemini-3-flash` for cost efficiency (brief generation is high-volume).
- Context caching enabled for system prompts — reduces cost by caching the repeated system prompt across calls.
- `response_schema` (Gemini JSON mode) for structured score outputs — ensures LLM returns a number, not prose.
- All LLM calls have a timeout and fallback path (template-based brief / keyword-heuristic score).

---

### 5.3 StorageClient

**File:** `app/integrations/storage.py`

```python
class StorageClient:
    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str):
        self.client = boto3.client("s3", endpoint_url=endpoint, ...)
        self.bucket = bucket

    async def upload_snapshot(
        self,
        content: str,
        property_id: str,
        page_type: str,
    ) -> str:
        """Upload raw HTML snapshot. Returns S3 path.
        Path: snapshots/{property_id}/{date}/{page_type}.html
        """

    async def get_snapshot(self, path: str) -> str:
        """Download raw HTML snapshot by path."""

    async def delete_expired_snapshots(self, older_than_days: int = 90) -> int:
        """Delete snapshots older than TTL. Returns count deleted.
        Uses S3 lifecycle policy in production. Manual cleanup for local dev.
        """
```

---

## 6. Shared Data Types

**File:** `app/schemas/common.py`

```python
@dataclass
class PaginatedResult(Generic[T]):
    data: list[T]
    total_count: int
    page_size: int
    cursor: str | None
    has_next: bool

class PropertyFilters(BaseModel):
    city: str | None = None
    property_types: list[str] | None = None
    statuses: list[str] | None = None
    min_score: float | None = None
    max_score: float | None = None
    has_phone: bool | None = None
    has_email: bool | None = None
    is_duplicate: bool = False
    search: str | None = None

class OutreachFilters(BaseModel):
    status: str | None = None
    assigned_to: UUID | None = None
    city: str | None = None
    min_priority: int | None = None
```

---

## 7. Error Handling

All services use a common set of domain exceptions:

```python
# app/exceptions.py

class FastRecceError(Exception):
    """Base exception for all domain errors."""

class NotFoundError(FastRecceError):
    """Entity not found. Maps to 404."""

class ConflictError(FastRecceError):
    """Duplicate or invalid state transition. Maps to 409."""

class ValidationError(FastRecceError):
    """Business rule violation. Maps to 422."""

class ExternalServiceError(FastRecceError):
    """Google API, LLM, or storage failure. Maps to 502."""

class RateLimitError(FastRecceError):
    """Rate limit exceeded. Maps to 429."""
```

The API layer catches these and maps to HTTP responses:

```python
# api/main.py
@app.exception_handler(NotFoundError)
async def not_found_handler(request, exc):
    return JSONResponse(status_code=404, content={
        "errors": [{"code": "NOT_FOUND", "message": str(exc)}]
    })
```

---

## 8. Service-to-Table Mapping

| Service | Reads | Writes |
|---|---|---|
| SourceService | sources | sources |
| QueryBankService | query_bank | query_bank |
| DiscoveryService | query_bank, property_sources (dedup check) | — (delegates to PropertyService) |
| CrawlerService | property_sources (hash check) | — (returns CrawlResult) |
| ContactService | property_contacts, do_not_contact | property_contacts, properties (canonical contacts) |
| DedupService | properties, property_contacts, property_media | properties (merge), property_sources, property_changes |
| PropertyService | properties, property_sources, property_contacts, property_media, outreach_queue | properties, property_sources, property_contacts, property_media, property_changes, outreach_queue |
| ScoringService | properties, property_contacts | properties (score fields) |
| BriefingService | properties | properties (brief fields) |
| OutreachService | outreach_queue, properties, users, do_not_contact | outreach_queue |
| PipelineService | crawl_runs | crawl_runs |

---

*Next Step: Frontend Data Flow Design → `/docs/frontend-design.md`*

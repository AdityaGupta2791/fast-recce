# FastRecce Platform — API Contract Specification

> **Document Version:** 1.0
> **Date:** 2026-04-13
> **Status:** Draft — Pending Confirmation
> **Depends On:** [database-schema.md](./database-schema.md), [system-architecture.md](./system-architecture.md)
> **Base URL:** `/api/v1`

---

## 1. API Design Principles

| Principle | Application |
|---|---|
| **RESTful resources** | URLs represent nouns (`/properties`), HTTP methods represent verbs (GET, POST, PATCH, DELETE). |
| **Consistent response envelope** | Every response uses `{ data, meta, errors }` structure. |
| **Cursor-based pagination** | For scored/ordered lists. Offset-based pagination breaks when scores change between pages. |
| **Explicit error codes** | Machine-readable error codes alongside human-readable messages. |
| **No over-fetching** | List endpoints return summary fields. Detail endpoints return full data. No `?fields=` complexity at MVP. |
| **Versioned** | `/api/v1/` prefix. Breaking changes get `/api/v2/`. |

---

## 2. Authentication

### Mechanism
JWT Bearer tokens. Stateless. No server-side session storage.

### Token Structure
- **Access Token:** 15-minute expiry. Sent in `Authorization: Bearer <token>` header.
- **Refresh Token:** 7-day expiry. Sent as HttpOnly cookie or in request body.

### Role-Based Access

| Role | Permissions |
|---|---|
| `admin` | Full access. Manage users, sources, queries. Delete/merge properties. |
| `reviewer` | View properties. Approve/reject. Add notes. Manage outreach queue. |
| `sales` | View approved properties. Manage assigned outreach items. |
| `viewer` | Read-only access to all data. |

---

## 3. Standard Response Format

### Success Response
```json
{
  "data": { ... },
  "meta": {
    "timestamp": "2026-04-13T10:30:00Z",
    "request_id": "req_abc123"
  }
}
```

### List Response (Paginated)
```json
{
  "data": [ ... ],
  "meta": {
    "total_count": 1234,
    "page_size": 50,
    "cursor": "eyJzY29yZSI6MC43NSwiaWQiOiJ4eHgifQ==",
    "has_next": true
  }
}
```

### Error Response
```json
{
  "errors": [
    {
      "code": "PROPERTY_NOT_FOUND",
      "message": "Property with id 'xxx' does not exist",
      "field": null
    }
  ],
  "meta": {
    "timestamp": "2026-04-13T10:30:00Z",
    "request_id": "req_abc123"
  }
}
```

### Standard Error Codes

| HTTP Status | Code | When |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Invalid request body or params |
| 401 | `UNAUTHORIZED` | Missing or expired token |
| 403 | `FORBIDDEN` | Valid token but insufficient role |
| 404 | `NOT_FOUND` | Resource doesn't exist |
| 409 | `CONFLICT` | Duplicate resource or status conflict |
| 422 | `UNPROCESSABLE` | Valid format but business rule violation |
| 429 | `RATE_LIMITED` | Too many requests |
| 500 | `INTERNAL_ERROR` | Unexpected server error |

---

## 4. API Endpoints

---

### 4.1 Authentication (`/auth`)

#### `POST /auth/login`
Authenticate user and return tokens.

**Access:** Public

**Request:**
```json
{
  "email": "reviewer@fastrecce.com",
  "password": "securepass123"
}
```

**Response (200):**
```json
{
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer",
    "expires_in": 900,
    "user": {
      "id": "uuid",
      "email": "reviewer@fastrecce.com",
      "full_name": "Rahul Sharma",
      "role": "reviewer"
    }
  }
}
```

**Errors:** `401 INVALID_CREDENTIALS`

---

#### `POST /auth/refresh`
Refresh access token.

**Access:** Public (requires valid refresh token)

**Request:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**Response (200):**
```json
{
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "expires_in": 900
  }
}
```

---

#### `GET /auth/me`
Get current user profile.

**Access:** Any authenticated user

**Response (200):**
```json
{
  "data": {
    "id": "uuid",
    "email": "reviewer@fastrecce.com",
    "full_name": "Rahul Sharma",
    "role": "reviewer",
    "is_active": true,
    "created_at": "2026-04-01T00:00:00Z"
  }
}
```

---

#### `GET /auth/users`
List all users.

**Access:** `admin` only

**Response (200):**
```json
{
  "data": [
    {
      "id": "uuid",
      "email": "reviewer@fastrecce.com",
      "full_name": "Rahul Sharma",
      "role": "reviewer",
      "is_active": true
    }
  ]
}
```

---

#### `POST /auth/users`
Create a new user.

**Access:** `admin` only

**Request:**
```json
{
  "email": "newuser@fastrecce.com",
  "full_name": "Priya Patel",
  "password": "securepass123",
  "role": "reviewer"
}
```

**Response (201):** User object (same as GET /auth/me shape)

**Errors:** `409 CONFLICT` (email already exists)

---

#### `PATCH /auth/users/:id`
Update user role or active status.

**Access:** `admin` only

**Request:**
```json
{
  "role": "sales",
  "is_active": false
}
```

**Response (200):** Updated user object

---

### 4.2 Properties (`/properties`)

#### `GET /properties`
List properties with filtering, sorting, and pagination. Primary endpoint for the Lead Queue view.

**Access:** Any authenticated user

**Query Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `city` | string | — | Filter by city (exact match) |
| `property_type` | string | — | Filter by type. Comma-separated for multiple: `villa,resort` |
| `status` | string | `new` | Filter by status. Comma-separated for multiple. |
| `min_score` | float | — | Minimum relevance score (0-1) |
| `max_score` | float | — | Maximum relevance score (0-1) |
| `has_phone` | boolean | — | Filter by phone availability |
| `has_email` | boolean | — | Filter by email availability |
| `is_duplicate` | boolean | `false` | Include/exclude duplicates |
| `search` | string | — | Full-text search on canonical_name, locality |
| `sort` | string | `relevance_score_desc` | Sort order (see below) |
| `cursor` | string | — | Pagination cursor from previous response |
| `page_size` | int | 50 | Items per page (max 100) |

**Sort Options:**
- `relevance_score_desc` (default)
- `relevance_score_asc`
- `created_at_desc`
- `created_at_asc`
- `canonical_name_asc`

**Response (200):**
```json
{
  "data": [
    {
      "id": "uuid",
      "canonical_name": "Sunset Heritage Villa",
      "city": "Alibaug",
      "locality": "Nagaon Beach Road",
      "property_type": "villa",
      "status": "new",
      "relevance_score": 0.82,
      "short_brief": "Heritage villa in Alibaug with open lawns, colonial architecture...",
      "canonical_phone": "+919876543210",
      "canonical_email": "info@sunsetvilla.com",
      "canonical_website": "https://sunsetvilla.com",
      "google_rating": 4.3,
      "source_count": 2,
      "contact_count": 4,
      "has_duplicate_warning": false,
      "created_at": "2026-04-13T06:00:00Z",
      "thumbnail_url": "https://..."
    }
  ],
  "meta": {
    "total_count": 342,
    "page_size": 50,
    "cursor": "eyJzIjowLjgyLCJpIjoieHh4In0=",
    "has_next": true
  }
}
```

**Notes:**
- List response returns summary fields only — no contacts array, no score breakdown, no change history.
- `source_count` and `contact_count` are computed counts, not nested arrays.
- `thumbnail_url` is the first image from `property_media` (if any).

---

#### `GET /properties/:id`
Full property detail. Primary endpoint for the Property Detail view.

**Access:** Any authenticated user

**Response (200):**
```json
{
  "data": {
    "id": "uuid",
    "canonical_name": "Sunset Heritage Villa",
    "normalized_address": "Nagaon Beach Road, Alibaug, Maharashtra 402201",
    "city": "Alibaug",
    "locality": "Nagaon Beach Road",
    "state": "Maharashtra",
    "pincode": "402201",
    "lat": 18.6414,
    "lng": 72.8722,
    "property_type": "villa",
    "status": "new",

    "canonical_website": "https://sunsetvilla.com",
    "canonical_phone": "+919876543210",
    "canonical_email": "info@sunsetvilla.com",

    "short_brief": "Heritage villa in Alibaug with open lawns...",
    "brief_generated_at": "2026-04-13T07:00:00Z",

    "relevance_score": 0.82,
    "score_breakdown": {
      "type_fit": 0.90,
      "shoot_fit": 0.85,
      "visual_uniqueness": 0.75,
      "location_demand": 0.80,
      "contact_completeness": 0.90,
      "website_quality": 0.70,
      "activity_recency": 0.80,
      "ease_of_outreach": 0.85
    },
    "scored_at": "2026-04-13T07:00:00Z",

    "features": {
      "amenities": ["lawn", "pool", "parking", "terrace"],
      "style_tags": ["heritage", "colonial", "rustic"],
      "capacity_cues": "8 rooms, large garden area",
      "special_notes": "Previously hosted brand shoots"
    },

    "google_place_id": "ChIJxxxxxx",
    "google_rating": 4.3,
    "google_review_count": 127,

    "is_duplicate": false,
    "duplicate_of": null,

    "sources": [
      {
        "id": "uuid",
        "source_name": "google_places",
        "source_url": "https://maps.google.com/?cid=xxx",
        "external_id": "ChIJxxxxxx",
        "discovered_at": "2026-04-12T06:00:00Z",
        "last_seen_at": "2026-04-13T06:00:00Z",
        "is_primary": true
      },
      {
        "id": "uuid",
        "source_name": "property_website",
        "source_url": "https://sunsetvilla.com",
        "discovered_at": "2026-04-12T06:30:00Z",
        "last_seen_at": "2026-04-13T06:30:00Z",
        "is_primary": false
      }
    ],

    "contacts": [
      {
        "id": "uuid",
        "contact_type": "phone",
        "contact_value": "+919876543210",
        "source_name": "google_places",
        "confidence": 0.95,
        "is_public_business_contact": true,
        "is_primary": true
      },
      {
        "id": "uuid",
        "contact_type": "email",
        "contact_value": "info@sunsetvilla.com",
        "source_name": "property_website",
        "confidence": 0.85,
        "is_public_business_contact": true,
        "is_primary": true
      }
    ],

    "media": [
      {
        "id": "uuid",
        "media_url": "https://...",
        "media_type": "image",
        "alt_text": "Villa exterior with garden",
        "sort_order": 0
      }
    ],

    "outreach": {
      "id": "uuid",
      "status": "pending",
      "assigned_to": null,
      "priority": 82,
      "suggested_angle": "Heritage property with proven event hosting..."
    },

    "created_at": "2026-04-12T06:00:00Z",
    "updated_at": "2026-04-13T07:00:00Z"
  }
}
```

**Notes:**
- Detail endpoint nests related data (sources, contacts, media, outreach) in a single response.
- This avoids N+1 frontend requests. One call loads the entire Property Detail view.
- `score_breakdown` is `score_reason_json` from DB, renamed for API clarity.
- `features` is `features_json` from DB, renamed.

---

#### `GET /properties/:id/changes`
Change history for a property.

**Access:** Any authenticated user

**Query Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `page_size` | int | 20 | Items per page |
| `cursor` | string | — | Pagination cursor |

**Response (200):**
```json
{
  "data": [
    {
      "id": "uuid",
      "change_type": "contact_updated",
      "field_name": "canonical_phone",
      "before_value": "+919876543210",
      "after_value": "+919876543211",
      "changed_by": null,
      "crawl_run_id": "uuid",
      "detected_at": "2026-04-13T06:00:00Z"
    }
  ],
  "meta": {
    "total_count": 5,
    "page_size": 20,
    "has_next": false
  }
}
```

---

#### `GET /properties/:id/duplicates`
Find potential duplicate properties for a given property.

**Access:** `reviewer`, `admin`

**Response (200):**
```json
{
  "data": [
    {
      "id": "uuid",
      "canonical_name": "Sunset Villa Resort",
      "city": "Alibaug",
      "property_type": "resort",
      "relevance_score": 0.65,
      "match_signals": {
        "name_similarity": 0.72,
        "distance_meters": 150,
        "phone_match": false,
        "website_match": false
      },
      "duplicate_confidence": 0.68
    }
  ]
}
```

---

#### `PATCH /properties/:id/review`
Perform a review action on a property. Primary endpoint for reviewer workflow.

**Access:** `reviewer`, `admin`

**Request — Approve:**
```json
{
  "action": "approve",
  "notes": "Strong candidate for Mumbai portfolio"
}
```

**Request — Reject:**
```json
{
  "action": "reject",
  "notes": "Not a shootable space, purely residential"
}
```

**Request — Mark Do-Not-Contact:**
```json
{
  "action": "do_not_contact",
  "notes": "Owner explicitly refused to be contacted"
}
```

**Request — Merge:**
```json
{
  "action": "merge",
  "merge_into_id": "uuid-of-canonical-property",
  "notes": "Same property, different listing"
}
```

**Valid Actions:**
| Action | Status Change | Side Effects |
|---|---|---|
| `approve` | `new` → `approved` | Creates outreach_queue entry if not exists |
| `reject` | `new` → `rejected` | — |
| `do_not_contact` | any → `do_not_contact` | Adds contacts to `do_not_contact` table |
| `merge` | current → `is_duplicate=true` | Links to canonical property, merges contacts/sources |
| `reopen` | `rejected` → `new` | — |

**Response (200):**
```json
{
  "data": {
    "id": "uuid",
    "status": "approved",
    "updated_at": "2026-04-13T10:30:00Z"
  }
}
```

**Errors:**
- `409 CONFLICT`: Invalid status transition (e.g., approving an already-onboarded property)
- `404 NOT_FOUND`: `merge_into_id` doesn't exist

---

#### `POST /properties/manual-import`
Manually import a property by URL (for restricted sources like Airbnb).

**Access:** `reviewer`, `admin`

**Request:**
```json
{
  "source_url": "https://www.airbnb.co.in/rooms/12345678",
  "source_name": "airbnb",
  "canonical_name": "Luxury Beachfront Villa, Alibaug",
  "city": "Alibaug",
  "locality": "Kihim Beach",
  "property_type": "villa",
  "contacts": [
    {
      "contact_type": "phone",
      "contact_value": "+919876543210",
      "is_public_business_contact": true
    }
  ],
  "notes": "Found during manual research. Owner is open to shoot bookings."
}
```

**Response (201):**
```json
{
  "data": {
    "id": "uuid",
    "canonical_name": "Luxury Beachfront Villa, Alibaug",
    "status": "new",
    "source_name": "airbnb",
    "created_at": "2026-04-13T10:30:00Z"
  }
}
```

**Notes:**
- This is how restricted-source properties enter the system — manually, with explicit analyst attribution.
- The system does NOT crawl the source URL if `access_policy = restricted`.
- `source_name` is validated against the `sources` table.

---

#### `POST /properties/:id/regenerate-brief`
Trigger AI brief regeneration for a property.

**Access:** `reviewer`, `admin`

**Response (202):**
```json
{
  "data": {
    "message": "Brief regeneration queued",
    "property_id": "uuid"
  }
}
```

---

### 4.3 Outreach (`/outreach`)

#### `GET /outreach`
List outreach queue items. Primary endpoint for the Outreach Pipeline (Kanban) view.

**Access:** `reviewer`, `sales`, `admin`

**Query Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `status` | string | — | Filter by outreach status. Comma-separated. |
| `assigned_to` | uuid | — | Filter by assigned user. Use `me` for current user. |
| `city` | string | — | Filter by property city |
| `min_priority` | int | — | Minimum priority (1-100) |
| `sort` | string | `priority_desc` | Sort order |
| `cursor` | string | — | Pagination cursor |
| `page_size` | int | 50 | Items per page |

**Sort Options:**
- `priority_desc` (default)
- `created_at_desc`
- `follow_up_at_asc` (for follow-up reminders)
- `last_contact_at_desc`

**Response (200):**
```json
{
  "data": [
    {
      "id": "uuid",
      "property": {
        "id": "uuid",
        "canonical_name": "Sunset Heritage Villa",
        "city": "Alibaug",
        "property_type": "villa",
        "relevance_score": 0.82,
        "canonical_phone": "+919876543210",
        "canonical_email": "info@sunsetvilla.com",
        "thumbnail_url": "https://..."
      },
      "status": "pending",
      "assigned_to": {
        "id": "uuid",
        "full_name": "Priya Patel"
      },
      "priority": 82,
      "outreach_channel": null,
      "suggested_angle": "Heritage property with proven event hosting...",
      "contact_attempts": 0,
      "first_contact_at": null,
      "last_contact_at": null,
      "follow_up_at": null,
      "notes": null,
      "created_at": "2026-04-13T08:00:00Z"
    }
  ],
  "meta": {
    "total_count": 45,
    "page_size": 50,
    "has_next": false
  }
}
```

---

#### `PATCH /outreach/:id`
Update outreach item (assign, change status, add notes).

**Access:** `reviewer`, `sales`, `admin`

**Request — Assign:**
```json
{
  "assigned_to": "user-uuid"
}
```

**Request — Log Contact Attempt:**
```json
{
  "status": "contacted",
  "outreach_channel": "phone",
  "notes": "Called, spoke with manager. Will call back Thursday."
}
```

**Request — Schedule Follow-up:**
```json
{
  "status": "follow_up",
  "follow_up_at": "2026-04-17T10:00:00Z",
  "notes": "Manager asked to call back after weekend"
}
```

**Request — Mark Converted:**
```json
{
  "status": "converted",
  "notes": "Owner agreed to onboard. Sending onboarding form."
}
```

**Valid Status Transitions:**

| From | To |
|---|---|
| `pending` | `contacted`, `declined` |
| `contacted` | `responded`, `follow_up`, `no_response`, `declined` |
| `responded` | `follow_up`, `converted`, `declined` |
| `follow_up` | `contacted`, `converted`, `declined`, `no_response` |
| `no_response` | `contacted`, `follow_up`, `declined` |

**Response (200):** Updated outreach item (same shape as list item)

**Errors:**
- `409 CONFLICT`: Invalid status transition
- `422 UNPROCESSABLE`: Contact blocked by `do_not_contact` list

---

#### `GET /outreach/stats`
Outreach funnel statistics.

**Access:** Any authenticated user

**Query Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `city` | string | — | Filter by city |
| `date_from` | date | 30 days ago | Start date |
| `date_to` | date | today | End date |

**Response (200):**
```json
{
  "data": {
    "total": 245,
    "by_status": {
      "pending": 45,
      "contacted": 67,
      "responded": 32,
      "follow_up": 28,
      "converted": 41,
      "declined": 19,
      "no_response": 13
    },
    "conversion_rate": 0.167,
    "avg_contact_attempts": 2.3,
    "avg_days_to_convert": 5.2
  }
}
```

---

### 4.4 Pipeline (`/pipeline`)

#### `GET /pipeline/runs`
List pipeline run history. Powers the Pipeline Health view.

**Access:** `admin`, `reviewer`

**Query Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `run_type` | string | — | Filter: `daily`, `weekly`, `monthly`, `manual` |
| `status` | string | — | Filter: `completed`, `failed`, `running` |
| `page_size` | int | 20 | Items per page |
| `cursor` | string | — | Pagination cursor |

**Response (200):**
```json
{
  "data": [
    {
      "id": "uuid",
      "run_type": "daily",
      "source_name": "google_places",
      "city": "Mumbai",
      "status": "completed",
      "started_at": "2026-04-13T02:00:00Z",
      "finished_at": "2026-04-13T02:25:00Z",
      "duration_seconds": 1500,
      "queries_executed": 48,
      "urls_processed": 312,
      "new_properties": 23,
      "updated_properties": 15,
      "skipped_duplicates": 89,
      "crawl_errors": 4
    }
  ],
  "meta": {
    "total_count": 30,
    "page_size": 20,
    "has_next": true
  }
}
```

---

#### `GET /pipeline/health`
Current pipeline health summary.

**Access:** `admin`, `reviewer`

**Response (200):**
```json
{
  "data": {
    "last_daily_run": {
      "id": "uuid",
      "status": "completed",
      "finished_at": "2026-04-13T02:25:00Z"
    },
    "last_weekly_run": {
      "id": "uuid",
      "status": "completed",
      "finished_at": "2026-04-10T04:00:00Z"
    },
    "properties_total": 4521,
    "properties_new": 342,
    "properties_approved": 1205,
    "properties_pending_score": 12,
    "properties_pending_brief": 8,
    "outreach_pending": 45,
    "sources": [
      {
        "source_name": "google_places",
        "is_enabled": true,
        "last_run_status": "completed",
        "last_run_at": "2026-04-13T02:00:00Z",
        "error_rate_7d": 0.02
      }
    ]
  }
}
```

---

#### `POST /pipeline/trigger`
Manually trigger a pipeline run.

**Access:** `admin` only

**Request:**
```json
{
  "run_type": "daily",
  "cities": ["Mumbai", "Pune"],
  "property_types": ["villa", "resort"]
}
```

**Response (202):**
```json
{
  "data": {
    "run_id": "uuid",
    "status": "pending",
    "message": "Pipeline run queued"
  }
}
```

---

### 4.5 Query Bank (`/queries`)

#### `GET /queries`
List all queries in the query bank.

**Access:** `admin`, `reviewer`

**Query Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `city` | string | — | Filter by city |
| `property_type` | string | — | Filter by property type |
| `is_enabled` | boolean | — | Filter by enabled status |
| `sort` | string | `quality_score_desc` | Sort order |
| `page_size` | int | 50 | Items per page |
| `cursor` | string | — | Pagination cursor |

**Response (200):**
```json
{
  "data": [
    {
      "id": "uuid",
      "query_text": "heritage bungalow in Mumbai",
      "city": "Mumbai",
      "locality": null,
      "property_type": "bungalow",
      "segment_tags": ["premium", "heritage", "residential"],
      "is_enabled": true,
      "last_run_at": "2026-04-13T02:00:00Z",
      "total_runs": 30,
      "total_results": 245,
      "new_properties": 67,
      "quality_score": 0.27
    }
  ],
  "meta": {
    "total_count": 156,
    "page_size": 50,
    "has_next": true
  }
}
```

---

#### `POST /queries`
Add a new query to the query bank.

**Access:** `admin`

**Request:**
```json
{
  "query_text": "film shooting location villa in Alibaug",
  "city": "Alibaug",
  "locality": null,
  "property_type": "villa",
  "segment_tags": ["premium", "outdoor", "film_friendly"]
}
```

**Response (201):** Query object

**Errors:** `409 CONFLICT` (duplicate query_text + city)

---

#### `PATCH /queries/:id`
Update a query (enable/disable, change tags).

**Access:** `admin`

**Request:**
```json
{
  "is_enabled": false,
  "segment_tags": ["premium", "outdoor"]
}
```

**Response (200):** Updated query object

---

#### `DELETE /queries/:id`
Delete a query from the bank.

**Access:** `admin`

**Response (204):** No content

---

### 4.6 Sources (`/sources`)

#### `GET /sources`
List all configured sources.

**Access:** `admin`

**Response (200):**
```json
{
  "data": [
    {
      "id": "uuid",
      "source_name": "google_places",
      "source_type": "api",
      "access_policy": "allowed",
      "crawl_method": "api_call",
      "base_url": "https://places.googleapis.com",
      "refresh_frequency": "daily",
      "parser_version": "1.0",
      "rate_limit_rpm": 60,
      "is_enabled": true,
      "notes": null
    }
  ]
}
```

---

#### `POST /sources`
Add a new source.

**Access:** `admin`

**Request:**
```json
{
  "source_name": "booking_com",
  "source_type": "partner_feed",
  "access_policy": "allowed",
  "crawl_method": "api_call",
  "base_url": "https://supply-xml.booking.com",
  "refresh_frequency": "daily",
  "rate_limit_rpm": 30
}
```

**Response (201):** Source object

---

#### `PATCH /sources/:id`
Update a source (enable/disable, change rate limit, update parser version).

**Access:** `admin`

**Request:**
```json
{
  "is_enabled": false,
  "rate_limit_rpm": 30
}
```

**Response (200):** Updated source object

---

### 4.7 Analytics (`/analytics`)

#### `GET /analytics/dashboard`
Dashboard-level summary statistics.

**Access:** Any authenticated user

**Response (200):**
```json
{
  "data": {
    "properties": {
      "total": 4521,
      "by_status": {
        "new": 342,
        "reviewed": 0,
        "approved": 1205,
        "rejected": 2831,
        "onboarded": 98,
        "do_not_contact": 45
      },
      "by_city": {
        "Mumbai": 1823,
        "Pune": 890,
        "Alibaug": 456,
        "Lonavala": 387,
        "Thane": 612,
        "Navi Mumbai": 353
      },
      "by_type": {
        "villa": 678,
        "resort": 512,
        "bungalow": 389,
        "boutique_hotel": 445,
        "farmhouse": 234,
        "other": 2263
      },
      "added_today": 23,
      "added_this_week": 156
    },
    "outreach": {
      "pending": 45,
      "in_progress": 127,
      "converted_this_month": 12,
      "conversion_rate": 0.167
    },
    "pipeline": {
      "last_run_status": "completed",
      "last_run_at": "2026-04-13T02:25:00Z",
      "error_rate_7d": 0.02
    }
  }
}
```

---

#### `GET /analytics/score-distribution`
Distribution of relevance scores across properties.

**Access:** Any authenticated user

**Query Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `city` | string | — | Filter by city |
| `property_type` | string | — | Filter by type |

**Response (200):**
```json
{
  "data": {
    "buckets": [
      { "range": "0.0-0.1", "count": 45 },
      { "range": "0.1-0.2", "count": 123 },
      { "range": "0.2-0.3", "count": 289 },
      { "range": "0.3-0.4", "count": 456 },
      { "range": "0.4-0.5", "count": 678 },
      { "range": "0.5-0.6", "count": 890 },
      { "range": "0.6-0.7", "count": 756 },
      { "range": "0.7-0.8", "count": 534 },
      { "range": "0.8-0.9", "count": 312 },
      { "range": "0.9-1.0", "count": 89 }
    ],
    "mean": 0.52,
    "median": 0.49,
    "p90": 0.78
  }
}
```

---

#### `GET /analytics/export`
Export filtered property data as CSV.

**Access:** `admin`, `reviewer`

**Query Parameters:** Same as `GET /properties` (city, property_type, status, min_score, etc.)

**Response (200):**
```
Content-Type: text/csv
Content-Disposition: attachment; filename="fastrecce-export-2026-04-13.csv"
```

CSV columns: id, canonical_name, city, locality, property_type, status, relevance_score, canonical_phone, canonical_email, canonical_website, short_brief, source_urls, created_at

---

## 5. Endpoint Summary

| Method | Endpoint | Module | Access | Purpose |
|---|---|---|---|---|
| POST | `/auth/login` | Auth | Public | Login |
| POST | `/auth/refresh` | Auth | Public | Refresh token |
| GET | `/auth/me` | Auth | Any | Current user |
| GET | `/auth/users` | Auth | Admin | List users |
| POST | `/auth/users` | Auth | Admin | Create user |
| PATCH | `/auth/users/:id` | Auth | Admin | Update user |
| GET | `/properties` | M9 | Any | Lead queue list |
| GET | `/properties/:id` | M9 | Any | Property detail |
| GET | `/properties/:id/changes` | M9 | Any | Change history |
| GET | `/properties/:id/duplicates` | M9 | Reviewer+ | Duplicate candidates |
| PATCH | `/properties/:id/review` | M9 | Reviewer+ | Review action |
| POST | `/properties/manual-import` | M9 | Reviewer+ | Manual property import |
| POST | `/properties/:id/regenerate-brief` | M8 | Reviewer+ | Regenerate AI brief |
| GET | `/outreach` | M9 | Reviewer+ | Outreach queue list |
| PATCH | `/outreach/:id` | M9 | Reviewer+ | Update outreach item |
| GET | `/outreach/stats` | M9 | Any | Outreach funnel stats |
| GET | `/pipeline/runs` | M10 | Reviewer+ | Pipeline run history |
| GET | `/pipeline/health` | M10 | Reviewer+ | Pipeline health summary |
| POST | `/pipeline/trigger` | M10 | Admin | Manual pipeline trigger |
| GET | `/queries` | M2 | Reviewer+ | List queries |
| POST | `/queries` | M2 | Admin | Add query |
| PATCH | `/queries/:id` | M2 | Admin | Update query |
| DELETE | `/queries/:id` | M2 | Admin | Delete query |
| GET | `/sources` | M1 | Admin | List sources |
| POST | `/sources` | M1 | Admin | Add source |
| PATCH | `/sources/:id` | M1 | Admin | Update source |
| GET | `/analytics/dashboard` | M9 | Any | Dashboard stats |
| GET | `/analytics/score-distribution` | M9 | Any | Score histogram |
| GET | `/analytics/export` | M9 | Reviewer+ | CSV export |

**Total: 28 endpoints**

---

## 6. API-to-Database Mapping

Shows which tables each endpoint reads/writes:

| Endpoint Group | Reads | Writes |
|---|---|---|
| `/auth/*` | users | users |
| `GET /properties` | properties | — |
| `GET /properties/:id` | properties, property_sources, property_contacts, property_media, outreach_queue | — |
| `PATCH /properties/:id/review` | properties, do_not_contact | properties, outreach_queue, property_changes, do_not_contact |
| `POST /properties/manual-import` | sources | properties, property_sources, property_contacts, property_changes |
| `/outreach/*` | outreach_queue, properties, users | outreach_queue |
| `/pipeline/*` | crawl_runs | crawl_runs (trigger only) |
| `/queries/*` | query_bank | query_bank |
| `/sources/*` | sources | sources |
| `/analytics/*` | properties, outreach_queue, crawl_runs | — |

---

## 7. Rate Limiting

| Scope | Limit | Purpose |
|---|---|---|
| Per-user, all endpoints | 100 req/min | Prevent runaway frontend bugs |
| `/analytics/export` | 5 req/min | CSV export is expensive |
| `/pipeline/trigger` | 3 req/hour | Prevent accidental pipeline spam |
| `/properties/manual-import` | 30 req/min | Reasonable manual import rate |

Implemented via Redis token bucket. Returns `429` with `Retry-After` header.

---

*Next Step: Confirm, then we proceed to define the backend service layer design → `/docs/service-design.md`*

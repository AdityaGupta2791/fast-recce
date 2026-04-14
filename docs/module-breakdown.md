# FastRecce Platform — Module Breakdown

> **Document Version:** 1.0
> **Date:** 2026-04-13
> **Status:** Draft — Pending Confirmation
> **Author:** Architecture Team

---

## 1. System Identity

**FastRecce Location Acquisition OS** is an internal platform that discovers properties with filming potential from compliant data sources, enriches them with contact and feature data, scores them for shoot relevance, and feeds a human-reviewed outreach pipeline.

**It is NOT:**
- A generic real-estate scraper
- A property marketplace
- An automated outreach bot

**It IS:**
- A location acquisition engine
- A shoot-relevance scoring system
- A compliance-aware data pipeline
- A human-in-the-loop outreach tool

---

## 2. Overall System Responsibilities

| Responsibility | Description |
|---|---|
| **Discover** | Find properties with filming potential via API-first and compliant sources |
| **Enrich** | Crawl property websites to extract contacts, features, and media |
| **Deduplicate** | Merge multiple source records into a single canonical property entity |
| **Score** | Rank properties by shoot-relevance using a weighted scoring formula |
| **Brief** | Generate AI-powered operational summaries for each property |
| **Review** | Surface scored properties to human reviewers for approval/rejection |
| **Outreach** | Manage the pipeline from approved lead to sales/onboarding handoff |
| **Comply** | Enforce source-aware rules on what data can be stored and how contacts are used |
| **Operate** | Schedule daily/weekly/monthly pipeline cycles with observability |

---

## 3. Core System Modules

The system is decomposed into **10 modules**. The PRD describes 5 "layers" — this breakdown refines that into properly bounded modules with clear ownership, inputs, and outputs.

---

### Module 1: Source Registry

**Purpose:** Define and manage all data sources the system interacts with, including their access policies, crawl methods, and compliance rules.

**Why it's a module:** The PRD correctly identifies that sources should not be hardcoded. This module is the control plane that tells every other module *how* to interact with each source.

| Attribute | Detail |
|---|---|
| **Owner** | Platform/Config team |
| **Data Entities** | `sources` |
| **Key Fields** | source_name, source_type, access_policy, crawl_method, refresh_frequency, parser_version, enabled_flag |
| **Inputs** | Admin configuration |
| **Outputs** | Source rules consumed by Discovery, Crawl, and Compliance modules |
| **Dependencies** | None (foundational module) |

**Key Design Decisions:**
- Source registry is a configuration table, not a service with complex logic
- `access_policy` enum: `allowed`, `manual_only`, `restricted` — enforced at pipeline level
- `crawl_method` enum: `api_call`, `sitemap`, `html_parser`, `browser_render`
- Adding a new source should require only a DB insert + a parser implementation, zero changes to pipeline code

---

### Module 2: Query Bank

**Purpose:** Manage the structured set of search queries that drive property discovery. Queries are segmented by city, locality, property type, and theme.

**Why it's a separate module (not in PRD as a module):** The query bank is the single biggest lever on discovery quality. It determines *what* the system finds. It needs versioning, performance tracking, and tuning — not just a static list.

| Attribute | Detail |
|---|---|
| **Owner** | Operations/Growth team |
| **Data Entities** | `query_bank` |
| **Key Fields** | query_text, city, locality, property_type, segment_tags (premium/budget, indoor/outdoor, etc.), enabled, last_run_at, results_count, quality_score |
| **Inputs** | Manual curation, monthly tuning from reviewer feedback |
| **Outputs** | Query list consumed by Discovery Engine |
| **Dependencies** | None |

**Key Design Decisions:**
- Queries are data, not code — stored in DB, editable via dashboard
- Track per-query yield (how many new properties each query discovers) to prune low-value queries
- Segment tags enable filtered discovery runs (e.g., "run only premium villa queries for Alibaug today")

---

### Module 3: Discovery Engine

**Purpose:** Execute queries against discovery sources (primarily Google Places API) and produce a list of candidate place IDs / URLs for further enrichment.

**Why it matters:** This is the top of the funnel. It runs daily and determines the raw input volume for the entire pipeline.

| Attribute | Detail |
|---|---|
| **Owner** | Backend/Pipeline team |
| **Data Entities** | `discovery_candidates` (staging table) |
| **Key Fields** | external_id (place_id), source_name, query_id, raw_result_json, discovered_at, processing_status |
| **Inputs** | Query Bank queries, Source Registry rules |
| **Outputs** | Candidate records ready for crawl/extraction |
| **Dependencies** | Module 1 (Source Registry), Module 2 (Query Bank) |

**Key Design Decisions:**
- Discovery is separated from extraction — discover first, enrich later
- Dedupe at discovery stage: skip candidates whose `external_id` already exists in `property_sources`
- Respect API rate limits and quotas (Google Places API has per-request and daily limits)
- Store raw API responses for auditability

**Integration Points:**
- Google Places Text Search API → candidate generation
- Google Places Details API → initial structured data (phone, website, rating)

---

### Module 4: Crawl & Extraction Engine

**Purpose:** For each discovered property, crawl its website and extract structured + unstructured data (contacts, features, media, schema markup).

**Why it's separate from Discovery:** Discovery finds *that* a property exists. Crawl/Extraction finds *details about* that property. Different cadence, different failure modes, different retry logic.

| Attribute | Detail |
|---|---|
| **Owner** | Backend/Pipeline team |
| **Data Entities** | `crawl_runs`, `raw_snapshots` |
| **Key Fields** | property_id, source_url, pages_crawled, raw_html_path, extracted_contacts_json, extracted_features_json, crawl_status |
| **Inputs** | Discovery candidates with website URLs |
| **Outputs** | Extracted data passed to Contact Resolver, Property Normalizer |
| **Dependencies** | Module 3 (Discovery Engine), Module 1 (Source Registry for crawl_method) |

**Sub-components:**
1. **Page Fetcher** — HTTP client (requests/httpx) for static pages, Playwright for JS-rendered pages
2. **Structured Extractor** — Parses schema.org/JSON-LD, tel/mailto links, address blocks
3. **Unstructured Extractor** — Free text parsing for about sections, FAQs, amenities, captions
4. **Media Extractor** — Collects image URLs, alt text, computes perceptual hashes
5. **Snapshot Store** — Archives raw HTML to S3-compatible storage with content hashing

**Key Design Decisions:**
- Crawl only allowed pages: home, contact, about, venue/event, footer — not the entire site
- Respect robots.txt
- Use content hashing (`raw_snapshot_hash`) to detect unchanged pages and skip re-processing
- Two extractor modes as PRD specifies: structured + unstructured

---

### Module 5: Contact Resolution

**Purpose:** Consolidate contacts from multiple extraction sources into verified, deduplicated contact records per property. Apply compliance rules.

**Why it's separate from Crawl:** Contact data has compliance implications. It needs its own validation, dedup, and audit trail — not just raw extraction.

| Attribute | Detail |
|---|---|
| **Owner** | Backend team |
| **Data Entities** | `property_contacts` |
| **Key Fields** | property_id, contact_type, contact_value, source_name, source_url, confidence, is_public_business_contact, first_seen_at, last_seen_at |
| **Inputs** | Extracted contact data from Crawl module |
| **Outputs** | Verified contacts on the canonical property entity |
| **Dependencies** | Module 4 (Crawl), Module 8 (Compliance for filtering) |

**Contact Precedence (from PRD):**
1. Structured business phone from API
2. Phone numbers on contact/footer pages
3. Mailto links
4. Explicit email strings in text
5. Contact forms
6. WhatsApp links
7. Instagram bio links (secondary only)

**Key Design Decisions:**
- Flag personal-looking contacts (e.g., gmail/yahoo emails, mobile-only numbers) for manual review
- Compute `confidence` score based on source reliability and extraction method
- `is_public_business_contact` boolean — only public business contacts are auto-approved

---

### Module 6: Deduplication Engine

**Purpose:** Detect and merge duplicate property records that originate from different sources or queries.

**Why it's a dedicated module:** The PRD explicitly warns "never rely on title match alone." Dedup is a multi-signal matching problem that grows in complexity with scale.

| Attribute | Detail |
|---|---|
| **Owner** | Backend/Data team |
| **Data Entities** | `property_sources` (linking table), `properties` (merge target) |
| **Key Fields** | duplicate_confidence, merge_candidate_ids, merge_status |
| **Inputs** | Newly extracted property data |
| **Outputs** | Merged canonical property records, duplicate warnings for review |
| **Dependencies** | Module 4 (Crawl), Module 5 (Contacts) |

**Matching Signals (from PRD):**
- Normalized name similarity (fuzzy match)
- Phone number match
- Website domain match
- Geo distance (lat/lng within threshold)
- Image perceptual hash similarity
- Same source URL or Google Place ID

**Key Design Decisions:**
- High-confidence matches (same place_id, same phone + geo) auto-merge
- Medium-confidence matches surface as "duplicate warning" on dashboard for human decision
- Maintain full source history in `property_sources` even after merge
- Run dedup both at ingestion time (real-time) and as weekly batch pass

---

### Module 7: Relevance Scoring Engine

**Purpose:** Score each property on shoot-relevance using a weighted formula. Generate score explanations.

**Why it's the core differentiator (per PRD):** This is what makes FastRecce a location *acquisition* tool rather than a generic directory. The score determines what surfaces to reviewers.

| Attribute | Detail |
|---|---|
| **Owner** | Product/ML team |
| **Data Entities** | `properties.relevance_score`, `properties.score_reason_json` |
| **Inputs** | Property features, contacts, media, location data |
| **Outputs** | Numeric score (0-1) + JSON explanation per property |
| **Dependencies** | Module 4 (features), Module 5 (contact completeness), Module 6 (dedup risk) |

**Scoring Formula (from PRD):**
```
relevance_score = 0.20 * type_fit
                + 0.20 * shoot_fit
                + 0.15 * visual_uniqueness
                + 0.10 * location_demand
                + 0.10 * contact_completeness
                + 0.10 * website_quality
                + 0.10 * activity_recency
                + 0.05 * ease_of_outreach
```

**Key Design Decisions:**
- Each sub-score is computed independently by a dedicated scorer function
- `score_reason_json` stores per-factor scores and reasoning — powers the dashboard explanation
- Scores are recomputed on property update, not just at discovery
- Monthly recalibration from reviewer accept/reject feedback (supervised signal)
- LLM-assisted scoring for subjective factors (visual_uniqueness, shoot_fit) using extracted text/features

---

### Module 8: AI Brief Generator

**Purpose:** Generate short, operational summaries for each property that help reviewers make fast decisions.

**Why it's separate from Scoring:** Brief generation requires LLM inference and depends on *both* extracted data and scoring signals. It's a distinct pipeline step with its own latency and cost profile.

| Attribute | Detail |
|---|---|
| **Owner** | Backend/AI team |
| **Data Entities** | `properties.short_brief` |
| **Inputs** | Property features, contacts, scores, media metadata |
| **Outputs** | 2-3 sentence operational brief per property |
| **Dependencies** | Module 4 (features), Module 7 (scores) |

**Brief Format (from PRD):**
> "Premium hillside resort in Lonavala with open lawns, poolside area, multiple room types, and scenic exterior frames. Strong fit for ad shoots, music videos, and branded hospitality content. Public website and direct phone available."

**Key Design Decisions:**
- Tone: operational, not marketing — helps reviewer decide, not sell
- Include: property type, location, key features, shoot fit, contact availability
- LLM call with structured prompt template + property context
- Cache briefs — regenerate only when property data changes significantly

---

### Module 9: Review & Outreach Dashboard

**Purpose:** Internal web application where human reviewers evaluate scored properties, approve/reject leads, and manage the outreach pipeline.

**Why it's a full module:** The PRD describes a rich set of reviewer actions. This is the primary human interface to the system.

| Attribute | Detail |
|---|---|
| **Owner** | Frontend + Backend team |
| **Data Entities** | `outreach_queue`, `property_changes`, `users` |
| **Inputs** | Scored and briefed properties from pipeline |
| **Outputs** | Reviewer decisions, outreach assignments, feedback signals |
| **Dependencies** | Module 7 (scores), Module 8 (briefs), Module 5 (contacts), Module 6 (dedup warnings) |

**Dashboard Views:**
1. **Lead Queue** — New properties sorted by relevance score, filterable by city/type/score range
2. **Property Detail** — Preview, source URLs, contacts, AI brief, score breakdown, duplicate warnings
3. **Outreach Pipeline** — Kanban-style board: pending → contacted → responded → onboarded / rejected
4. **Crawl Health** — Pipeline run status, error rates, source health
5. **Query Performance** — Per-query yield, helping tune the query bank

**Reviewer Actions (from PRD):**
- Approve for outreach
- Reject
- Merge with existing property
- Mark as restricted / do-not-contact
- Assign to sales/onboarding team member
- Add manual notes

---

### Module 10: Pipeline Orchestrator

**Purpose:** Schedule and coordinate all pipeline stages (discovery, crawl, scoring, etc.) on daily/weekly/monthly cadences with observability.

**Why it's a module:** The PRD defines three cadences (daily, weekly, monthly) with different task sets. This needs a proper scheduler, not ad-hoc cron jobs.

| Attribute | Detail |
|---|---|
| **Owner** | Platform/DevOps team |
| **Data Entities** | `crawl_runs`, `pipeline_jobs` |
| **Inputs** | Schedule configuration, Source Registry |
| **Outputs** | Triggered pipeline runs with status tracking |
| **Dependencies** | All pipeline modules (3, 4, 5, 6, 7, 8) |

**Cadence (from PRD):**

| Cycle | Tasks |
|---|---|
| **Daily** | Discovery → Place Details → Website Crawl → Contact Resolution → Dedup (fast) → Score → Brief → Push to Dashboard |
| **Weekly** | Deep enrichment on high-priority properties, full dedup pass, dead-link cleanup, score recalibration, export report |
| **Monthly** | Tune query bank, review false positives, add/remove source rules, retrain scoring heuristics |

**Key Design Decisions:**
- Use a proper workflow orchestrator (Prefect recommended over raw cron — better retry/observability)
- Each pipeline stage is an independent task with clear input/output contracts
- Failed stages don't block the entire pipeline — partial results are still useful
- `crawl_runs` table provides full audit trail of every pipeline execution

---

## 4. Cross-Cutting Concern: Compliance Engine

**Not a standalone module but enforced across modules 3-6.**

| Rule | Enforcement Point |
|---|---|
| Store only public business contact data | Module 5 (Contact Resolution) |
| Flag personal contacts for manual review | Module 5 → Module 9 (Dashboard) |
| Maintain do-not-contact list | Module 5 + Module 9 |
| Never scrape restricted sources automatically | Module 1 (Source Registry) + Module 3 (Discovery) |
| Never auto-message restricted-source contacts | Module 9 (Outreach) |
| Log provenance of every phone/email | Module 5 (source_url, source_name fields) |
| Keep source URLs for auditability | Module 4 (Crawl) + Module 5 (Contacts) |

---

## 5. Module Dependency Graph

```
                    ┌──────────────┐
                    │   Module 1   │
                    │Source Registry│
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            │
     ┌──────────────┐ ┌──────────┐     │
     │   Module 2   │ │ Module 10│     │
     │  Query Bank  │ │Orchestrat│     │
     └──────┬───────┘ └────┬─────┘     │
            │              │           │
            ▼              │           │
     ┌──────────────┐      │           │
     │   Module 3   │◄─────┘           │
     │  Discovery   │                  │
     └──────┬───────┘                  │
            │                          │
            ▼                          │
     ┌──────────────┐                  │
     │   Module 4   │◄────────────────┘
     │ Crawl/Extract│
     └──────┬───────┘
            │
       ┌────┼────┐
       │         │
       ▼         ▼
┌──────────┐ ┌──────────┐
│ Module 5 │ │ Module 6 │
│ Contacts │ │  Dedup   │
└────┬─────┘ └────┬─────┘
     │            │
     └─────┬──────┘
           │
           ▼
    ┌──────────────┐
    │   Module 7   │
    │   Scoring    │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │   Module 8   │
    │  AI Briefs   │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │   Module 9   │
    │  Dashboard   │
    └──────────────┘
```

---

## 6. Module Build Order (Recommended)

Based on dependencies, the implementation order should be:

| Phase | Modules | Rationale |
|---|---|---|
| **Phase 1** | M1 (Source Registry), M2 (Query Bank) | Foundation — zero dependencies, everything else reads from these |
| **Phase 2** | M3 (Discovery Engine) | Top of the data funnel — needs M1 + M2 |
| **Phase 3** | M4 (Crawl/Extract), M5 (Contacts), M6 (Dedup) | Core data pipeline — can be built in parallel |
| **Phase 4** | M7 (Scoring), M8 (AI Briefs) | Intelligence layer — needs enriched data from Phase 3 |
| **Phase 5** | M9 (Dashboard), M10 (Orchestrator) | Human interface + automation — built on top of everything |

---

## 7. PRD Gaps & Architect Recommendations

| Gap | Recommendation |
|---|---|
| **No user/auth model** | Add a simple `users` table with roles (admin, reviewer, sales). Use Supabase Auth or simple JWT. |
| **Query Bank is not a managed entity** | Promote to first-class module with performance tracking (added as Module 2). |
| **AI Brief depends on scoring but PRD places it in Layer 3** | Moved brief generation after scoring (Module 8 depends on Module 7). |
| **No explicit change detection model** | The `property_changes` table exists in the DB schema but no module owns it. Assign to Module 4 (Crawl) — detect changes via snapshot hash diff. |
| **Compliance is "guardrails" not a module** | Made it a cross-cutting concern with explicit enforcement points per module. |
| **No observability / alerting mentioned** | Module 10 (Orchestrator) should emit metrics: discovery yield, crawl success rate, scoring distribution, queue depth. |
| **No data retention policy** | Raw snapshots should have a TTL (e.g., 90 days). Canonical data is permanent. Define in Source Registry. |
| **Export/reporting mentioned but not designed** | Add export capability to Module 9 (Dashboard) — CSV/Excel export of filtered lead lists. |

---

## 8. MVP Scope Alignment

The PRD's 4-week MVP maps to these modules:

| Week | PRD Tasks | Modules |
|---|---|---|
| Week 1 | Source policy matrix, Google query bank, DB schema, crawler skeleton, dashboard wireframe | M1, M2, DB setup, M4 skeleton, M9 wireframe |
| Week 2 | Google discovery, website crawler, contact extractor, dedupe logic | M3, M4, M5, M6 |
| Week 3 | Relevance scoring, AI brief, review dashboard, outreach queue | M7, M8, M9 |
| Week 4 | Daily scheduler, QA, reviewer workflow, export | M10, M9 polish, QA |

**MVP Cities:** Mumbai, Thane, Navi Mumbai, Lonavala/Khandala, Pune, Alibaug

---

*Next Step: System Architecture Design → `/docs/system-architecture.md`*

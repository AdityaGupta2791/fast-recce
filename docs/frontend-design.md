# FastRecce Platform — Frontend Data Flow Design

> **Document Version:** 1.0
> **Date:** 2026-04-13
> **Status:** Draft — Pending Confirmation
> **Depends On:** [api-spec.md](./api-spec.md), [system-architecture.md](./system-architecture.md)

---

## 1. Frontend Architecture Overview

| Decision | Choice | Reasoning |
|---|---|---|
| **Rendering** | Client-side SPA | Internal tool. No SEO. No SSR complexity. |
| **Framework** | React 18 + TypeScript | PRD spec. Type safety on API contracts. |
| **Routing** | React Router v7 | Flat route structure. No nested layouts beyond shell. |
| **Data Fetching** | TanStack Query v5 | Server-state management. Auto-refetch, caching, optimistic updates. |
| **Client State** | React Context (auth only) | No Redux. Only auth state is truly client-side. Everything else is server state managed by TanStack Query. |
| **Styling** | Tailwind CSS + shadcn/ui | Utility-first. Copy-paste components. No version lock-in. |
| **Forms** | React Hook Form + Zod | Performant forms. Schema validation matching API contracts. |
| **Charts** | Recharts | Lightweight. Score distribution histogram, funnel chart. |
| **Tables** | TanStack Table v8 | Headless table with sorting, filtering, pagination. |
| **Build** | Vite | Fast HMR in dev. Optimized production builds. |

---

## 2. Route Structure

```
/                       → Redirect to /leads
/login                  → Login page (public)

/leads                  → Lead Queue (default view)
/properties/:id         → Property Detail
/outreach               → Outreach Pipeline (Kanban)
/pipeline               → Pipeline Health
/queries                → Query Bank Manager
/sources                → Source Registry (admin only)
/users                  → User Management (admin only)
/analytics              → Analytics Dashboard
```

**Route-to-Role Mapping:**

| Route | viewer | reviewer | sales | admin |
|---|---|---|---|---|
| `/leads` | read | read + review actions | read | full |
| `/properties/:id` | read | read + review/merge | read | full |
| `/outreach` | read | full | own assignments | full |
| `/pipeline` | — | read | — | full + trigger |
| `/queries` | — | read | — | full CRUD |
| `/sources` | — | — | — | full CRUD |
| `/users` | — | — | — | full CRUD |
| `/analytics` | read | read | read | read |

---

## 3. Application Shell

```
┌──────────────────────────────────────────────────────────┐
│  Sidebar (fixed)            │  Main Content Area          │
│                             │                             │
│  ┌───────────────────────┐  │  ┌─────────────────────────┐│
│  │ FastRecce Logo        │  │  │  Page Header            ││
│  ├───────────────────────┤  │  │  (title + actions)      ││
│  │ 📋 Lead Queue    (342)│  │  ├─────────────────────────┤│
│  │ 📞 Outreach       (45)│  │  │                         ││
│  │ ⚙️  Pipeline           │  │  │  Page Content           ││
│  │ 🔍 Query Bank         │  │  │  (route-specific)       ││
│  │ 📊 Analytics          │  │  │                         ││
│  │ ─────────────────     │  │  │                         ││
│  │ 🔧 Sources  (admin)   │  │  │                         ││
│  │ 👥 Users    (admin)   │  │  │                         ││
│  ├───────────────────────┤  │  │                         ││
│  │ User: Rahul S.        │  │  │                         ││
│  │ Role: reviewer        │  │  │                         ││
│  │ [Logout]              │  │  │                         ││
│  └───────────────────────┘  │  └─────────────────────────┘│
└──────────────────────────────────────────────────────────┘
```

**Shell Component:** `AppShell.tsx`
- Sidebar shows badge counts (new leads, pending outreach) — fetched via `/analytics/dashboard`
- Admin-only routes hidden for non-admin users
- Current user displayed at bottom, fetched from `AuthContext`

---

## 4. Page Designs & Data Flow

---

### 4.1 Lead Queue Page (`/leads`)

**Purpose:** Primary workspace for reviewers. Browse, filter, and take action on discovered properties.

**Layout:**

```
┌─────────────────────────────────────────────────────────┐
│  Lead Queue                           [Export CSV]       │
├─────────────────────────────────────────────────────────┤
│  Filters:                                                │
│  [City ▼] [Type ▼] [Status ▼] [Score: 0.5-1.0] [🔍  ] │
├─────────────────────────────────────────────────────────┤
│  ┌─────┬────────────────┬───────┬──────┬───────┬──────┐ │
│  │Score│ Property        │ City  │ Type │Contact│Action│ │
│  ├─────┼────────────────┼───────┼──────┼───────┼──────┤ │
│  │ 0.82│ Sunset Heritage│Alibaug│Villa │📞📧🌐│[···] │ │
│  │ 0.78│ Hilltop Resort │Lonav. │Resort│📞📧  │[···] │ │
│  │ 0.71│ Royal Bungalow │Mumbai │Bungl.│📞    │[···] │ │
│  │ ... │ ...            │ ...   │ ...  │ ...   │ ...  │ │
│  └─────┴────────────────┴───────┴──────┴───────┴──────┘ │
│                                                          │
│  Showing 1-50 of 342          [Load More]                │
└─────────────────────────────────────────────────────────┘
```

**Data Fetching:**

```typescript
// pages/LeadQueue.tsx

function LeadQueue() {
  const [filters, setFilters] = useState<PropertyFilters>(defaultFilters);

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isLoading,
  } = useInfiniteQuery({
    queryKey: ["properties", filters],
    queryFn: ({ pageParam }) =>
      api.properties.list({ ...filters, cursor: pageParam }),
    getNextPageParam: (lastPage) =>
      lastPage.meta.has_next ? lastPage.meta.cursor : undefined,
    staleTime: 30_000,       // 30s — data is relatively fresh
  });

  // Flatten pages for table
  const properties = data?.pages.flatMap((p) => p.data) ?? [];

  return (
    <div>
      <LeadFilters filters={filters} onChange={setFilters} />
      <PropertyTable
        data={properties}
        isLoading={isLoading}
        onLoadMore={fetchNextPage}
        hasMore={hasNextPage}
      />
    </div>
  );
}
```

**Component Breakdown:**

| Component | Props | Responsibility |
|---|---|---|
| `LeadQueue` (page) | — | Owns filter state, manages query |
| `LeadFilters` | filters, onChange | City/type/status/score filter controls |
| `PropertyTable` | data, isLoading, onLoadMore, hasMore | TanStack Table with columns, infinite scroll trigger |
| `PropertyRow` | property | Single row with score badge, contact icons, action menu |
| `QuickActionMenu` | propertyId | Dropdown: Approve, Reject, View Detail |
| `ScoreBadge` | score | Color-coded: green (>0.7), yellow (0.4-0.7), red (<0.4) |
| `ContactIcons` | contacts | Phone/email/website/WhatsApp presence indicators |
| `ExportButton` | filters | Triggers CSV export with current filters |

**Interactions:**

| Action | Flow |
|---|---|
| Change filter | `setFilters()` → TanStack Query refetches with new params → table re-renders |
| Scroll to bottom | `fetchNextPage()` → appends new page → table grows |
| Click property name | `navigate(/properties/${id})` → Property Detail page |
| Quick approve | `useMutation` → `PATCH /properties/:id/review` → invalidate `["properties"]` query → row updates |
| Export CSV | `window.open(/api/v1/analytics/export?${filterParams})` → browser downloads file |

**Optimistic Update (Quick Approve):**

```typescript
const reviewMutation = useMutation({
  mutationFn: (data: ReviewAction) =>
    api.properties.review(data.propertyId, data),
  onMutate: async (data) => {
    // Cancel refetches
    await queryClient.cancelQueries({ queryKey: ["properties"] });
    // Snapshot previous state
    const previous = queryClient.getQueryData(["properties", filters]);
    // Optimistically remove from list (approved → no longer "new")
    queryClient.setQueryData(["properties", filters], (old) =>
      removePropertyFromPages(old, data.propertyId)
    );
    return { previous };
  },
  onError: (err, data, context) => {
    // Rollback on error
    queryClient.setQueryData(["properties", filters], context.previous);
    toast.error("Review failed: " + err.message);
  },
  onSettled: () => {
    // Refetch to sync with server
    queryClient.invalidateQueries({ queryKey: ["properties"] });
    queryClient.invalidateQueries({ queryKey: ["analytics"] });
  },
});
```

---

### 4.2 Property Detail Page (`/properties/:id`)

**Purpose:** Full view of a single property. Reviewer makes informed approve/reject decisions here.

**Layout:**

```
┌──────────────────────────────────────────────────────────┐
│  ← Back to Queue                                         │
│                                                          │
│  Sunset Heritage Villa                    Status: [New ▼]│
│  Alibaug, Nagaon Beach Road              Score: ████ 0.82│
├─────────────────┬────────────────────────────────────────┤
│  Image Gallery  │  AI Brief                              │
│  ┌────┐ ┌────┐  │  "Heritage villa in Alibaug with open  │
│  │    │ │    │  │   lawns, colonial architecture, and    │
│  └────┘ └────┘  │   scenic frames. Strong fit for..."    │
│  ┌────┐ ┌────┐  │  [🔄 Regenerate Brief]                │
│  │    │ │    │  │                                        │
│  └────┘ └────┘  ├────────────────────────────────────────┤
│                 │  Score Breakdown                        │
│                 │  ┌─────────────────────────────┐        │
│                 │  │ Type Fit      ████████░░ 0.90│       │
│                 │  │ Shoot Fit     ████████░░ 0.85│       │
│                 │  │ Visual Uniq.  ██████░░░░ 0.75│       │
│                 │  │ Location Dem. ████████░░ 0.80│       │
│                 │  │ Contact Comp. █████████░ 0.90│       │
│                 │  │ Website Qual. ███████░░░ 0.70│       │
│                 │  │ Recency       ████████░░ 0.80│       │
│                 │  │ Ease Outreach ████████░░ 0.85│       │
│                 │  └─────────────────────────────┘        │
├─────────────────┴────────────────────────────────────────┤
│  Tabs: [Contacts] [Sources] [Media] [Changes]            │
├──────────────────────────────────────────────────────────┤
│  Contacts                                                │
│  📞 +91 9876543210  (google_places, conf: 0.95) ✅ Biz  │
│  📧 info@sunset.com (property_website, conf: 0.85) ✅ Biz│
│  💬 wa.me/919876..  (property_website, conf: 0.80) ✅ Biz│
├──────────────────────────────────────────────────────────┤
│  ⚠️ Duplicate Warning: "Sunset Villa Resort" (68% match) │
│     [View Duplicate] [Merge] [Dismiss]                   │
├──────────────────────────────────────────────────────────┤
│  Review Actions                                          │
│  [✅ Approve for Outreach]  [❌ Reject]  [🔗 Merge]      │
│  Notes: [________________________________] [Submit]       │
└──────────────────────────────────────────────────────────┘
```

**Data Fetching:**

```typescript
// pages/PropertyDetail.tsx

function PropertyDetail() {
  const { id } = useParams<{ id: string }>();

  // Single query loads all nested data
  const { data: property, isLoading } = useQuery({
    queryKey: ["property", id],
    queryFn: () => api.properties.get(id),
    staleTime: 60_000,
  });

  // Duplicate check (separate query — may be slow)
  const { data: duplicates } = useQuery({
    queryKey: ["property", id, "duplicates"],
    queryFn: () => api.properties.getDuplicates(id),
    staleTime: 300_000,   // 5 min — dedup data changes rarely
  });

  // Change history (lazy — only loads when tab selected)
  const [activeTab, setActiveTab] = useState("contacts");

  const { data: changes } = useQuery({
    queryKey: ["property", id, "changes"],
    queryFn: () => api.properties.getChanges(id),
    enabled: activeTab === "changes",  // Only fetch when tab active
  });

  // Review mutation
  const reviewMutation = useMutation({
    mutationFn: (action: ReviewAction) =>
      api.properties.review(id, action),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["property", id] });
      queryClient.invalidateQueries({ queryKey: ["properties"] });
      toast.success("Review saved");
    },
  });

  // Brief regeneration mutation
  const briefMutation = useMutation({
    mutationFn: () => api.properties.regenerateBrief(id),
    onSuccess: () => {
      toast.success("Brief regeneration queued");
      // Refetch after delay (brief generation is async)
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["property", id] });
      }, 5000);
    },
  });

  if (isLoading) return <PropertyDetailSkeleton />;
  if (!property) return <NotFound />;

  return (
    <div>
      <PropertyHeader property={property} />
      <div className="grid grid-cols-2 gap-6">
        <ImageGallery media={property.media} />
        <div>
          <AIBrief brief={property.short_brief} onRegenerate={briefMutation.mutate} />
          <ScoreBreakdown breakdown={property.score_breakdown} total={property.relevance_score} />
        </div>
      </div>
      <DetailTabs
        activeTab={activeTab}
        onTabChange={setActiveTab}
        contacts={property.contacts}
        sources={property.sources}
        media={property.media}
        changes={changes}
      />
      <DuplicateWarning duplicates={duplicates} propertyId={id} />
      <ReviewActions
        status={property.status}
        onReview={reviewMutation.mutate}
        isLoading={reviewMutation.isPending}
      />
    </div>
  );
}
```

**Component Breakdown:**

| Component | Data Source | Responsibility |
|---|---|---|
| `PropertyHeader` | property | Name, location, status badge, score |
| `ImageGallery` | property.media | Grid of images with lightbox |
| `AIBrief` | property.short_brief | Brief text + regenerate button |
| `ScoreBreakdown` | property.score_breakdown | Horizontal bar chart per factor |
| `DetailTabs` | property.contacts/sources/media/changes | Tabbed view of related data |
| `ContactList` | property.contacts | Contact rows with type icon, confidence, business flag |
| `SourceList` | property.sources | Source links with discovery/last-seen dates |
| `ChangeHistory` | changes (lazy loaded) | Timeline of property changes |
| `DuplicateWarning` | duplicates | Alert banner with merge/dismiss actions |
| `ReviewActions` | property.status | Action buttons + notes field |

---

### 4.3 Outreach Pipeline Page (`/outreach`)

**Purpose:** Kanban board for managing outreach workflow.

**Layout:**

```
┌──────────────────────────────────────────────────────────────────┐
│  Outreach Pipeline                     [Filter: My Items ▼]      │
├──────────┬──────────┬──────────┬──────────┬──────────┬──────────┤
│ Pending  │Contacted │Responded │Follow-Up │Converted │Declined  │
│   (45)   │   (67)   │   (32)   │   (28)   │   (41)   │   (19)  │
├──────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
│┌────────┐│┌────────┐│┌────────┐│┌────────┐│          │          │
││Sunset  ││ │Hilltop ││ │Royal  ││ │Ocean  ││          │          │
││Villa   ││ │Resort  ││ │Bungal.││ │View   ││          │          │
││Pri: 82 ││ │Pri: 78 ││ │Pri: 71││ │Due:   ││          │          │
││Alibaug ││ │Lonaval.││ │Mumbai ││ │Apr 17 ││          │          │
││📞📧🌐 ││ │📞📧   ││ │📞    ││ │📞📧  ││          │          │
│└────────┘│└────────┘│└────────┘│└────────┘│          │          │
│┌────────┐│┌────────┐│          │          │          │          │
││ ...    ││ │ ...   ││          │          │          │          │
│└────────┘│└────────┘│          │          │          │          │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
```

**Data Fetching:**

```typescript
// pages/OutreachPipeline.tsx

const STATUSES = ["pending", "contacted", "responded", "follow_up", "converted", "declined"];

function OutreachPipeline() {
  const [assigneeFilter, setAssigneeFilter] = useState<string>("all");

  // Fetch all outreach items (grouped client-side by status)
  const { data } = useQuery({
    queryKey: ["outreach", { assigned_to: assigneeFilter }],
    queryFn: () =>
      api.outreach.list({
        assigned_to: assigneeFilter === "me" ? "me" : undefined,
        page_size: 100,
      }),
    staleTime: 15_000,       // 15s — outreach changes frequently
  });

  // Stats for column headers
  const { data: stats } = useQuery({
    queryKey: ["outreach", "stats"],
    queryFn: () => api.outreach.getStats(),
    staleTime: 60_000,
  });

  // Group items by status
  const columns = useMemo(() => {
    const items = data?.data ?? [];
    return STATUSES.map((status) => ({
      status,
      count: stats?.data.by_status[status] ?? 0,
      items: items.filter((i) => i.status === status),
    }));
  }, [data, stats]);

  // Status change mutation
  const updateMutation = useMutation({
    mutationFn: ({ id, ...data }: OutreachUpdate & { id: string }) =>
      api.outreach.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["outreach"] });
    },
  });

  return (
    <div className="flex gap-4 overflow-x-auto">
      {columns.map((col) => (
        <KanbanColumn
          key={col.status}
          status={col.status}
          count={col.count}
          items={col.items}
          onStatusChange={(id, newStatus) =>
            updateMutation.mutate({ id, status: newStatus })
          }
        />
      ))}
    </div>
  );
}
```

**Component Breakdown:**

| Component | Responsibility |
|---|---|
| `OutreachPipeline` (page) | Owns query, groups data by status |
| `KanbanColumn` | Renders column header (status + count) and list of cards |
| `OutreachCard` | Single card: property name, priority, city, contact icons, quick actions |
| `OutreachDetailModal` | Modal on card click: full details, notes field, status change, assignment |
| `ContactAttemptForm` | Log a contact attempt: channel, notes, follow-up date |

**Interaction: Status Change**

```
User clicks "Mark Contacted" on a card
  → OutreachDetailModal opens
  → User selects channel (phone/email/whatsapp)
  → User adds notes
  → Submit → PATCH /outreach/:id { status: "contacted", outreach_channel: "phone", notes: "..." }
  → On success: invalidate outreach query → card moves to "Contacted" column
  → On error: toast.error with server message
```

---

### 4.4 Pipeline Health Page (`/pipeline`)

**Purpose:** Monitor pipeline execution status and health.

**Layout:**

```
┌──────────────────────────────────────────────────────────┐
│  Pipeline Health                     [▶ Trigger Run]     │
├──────────────────────────────────────────────────────────┤
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐        │
│  │ Last Daily   │ │ Properties  │ │ Error Rate  │        │
│  │ ✅ 2h ago    │ │ 4,521 total │ │ 2% (7d avg) │        │
│  │ 25 min       │ │ +23 today   │ │             │        │
│  └─────────────┘ └─────────────┘ └─────────────┘        │
├──────────────────────────────────────────────────────────┤
│  Source Health                                           │
│  ┌──────────────┬────────┬───────────┬────────┬────────┐│
│  │ Source       │ Status │ Last Run  │Errors  │Enabled ││
│  ├──────────────┼────────┼───────────┼────────┼────────┤│
│  │google_places │ ✅ OK  │ 2h ago    │ 2%     │ Yes    ││
│  │prop_website  │ ✅ OK  │ 2h ago    │ 5%     │ Yes    ││
│  │maharera      │ ⚠️ Warn │ 3d ago    │ 12%    │ Yes    ││
│  └──────────────┴────────┴───────────┴────────┴────────┘│
├──────────────────────────────────────────────────────────┤
│  Recent Runs                                             │
│  ┌──────┬──────┬────────┬──────┬─────┬───────┬────────┐ │
│  │ Type │ City │Started │ Dur. │ New │Errors │ Status │ │
│  ├──────┼──────┼────────┼──────┼─────┼───────┼────────┤ │
│  │daily │Mumbai│6:00 AM │25 min│ 15  │ 3     │ ✅     │ │
│  │daily │Pune  │6:30 AM │18 min│ 8   │ 1     │ ✅     │ │
│  │weekly│ All  │Mon 4AM │2.1 hr│ —   │ 7     │ ✅     │ │
│  └──────┴──────┴────────┴──────┴─────┴───────┴────────┘ │
└──────────────────────────────────────────────────────────┘
```

**Data Fetching:**

```typescript
// pages/PipelineHealth.tsx

function PipelineHealth() {
  const { data: health } = useQuery({
    queryKey: ["pipeline", "health"],
    queryFn: () => api.pipeline.getHealth(),
    refetchInterval: 30_000,  // Auto-refresh every 30s
  });

  const { data: runs } = useQuery({
    queryKey: ["pipeline", "runs"],
    queryFn: () => api.pipeline.listRuns({ page_size: 20 }),
    refetchInterval: 30_000,
  });

  const triggerMutation = useMutation({
    mutationFn: (config: PipelineTrigger) => api.pipeline.trigger(config),
    onSuccess: () => {
      toast.success("Pipeline run queued");
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    },
  });

  return ( ... );
}
```

**Notes:**
- Auto-refresh every 30 seconds (pipeline status changes are meaningful to watch during/after a run).
- Trigger button opens a modal: select run_type, cities, property_types. Admin only.

---

### 4.5 Query Bank Page (`/queries`)

**Purpose:** Manage and monitor discovery queries.

**Data Fetching:**

```typescript
function QueryManager() {
  const [filters, setFilters] = useState({ city: null, is_enabled: null });

  const { data: queries } = useQuery({
    queryKey: ["queries", filters],
    queryFn: () => api.queries.list(filters),
    staleTime: 60_000,
  });

  const createMutation = useMutation({
    mutationFn: (data: QueryCreate) => api.queries.create(data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queries"] }),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, ...data }: QueryUpdate & { id: string }) =>
      api.queries.update(id, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queries"] }),
  });

  return (
    <div>
      <QueryFilters ... />
      <QueryTable
        data={queries}
        onToggleEnabled={(id, enabled) => updateMutation.mutate({ id, is_enabled: enabled })}
      />
      <AddQueryModal onSubmit={createMutation.mutate} />
    </div>
  );
}
```

**Key columns:** query_text, city, property_type, quality_score (bar), total_runs, new_properties, enabled toggle.

---

### 4.6 Analytics Dashboard Page (`/analytics`)

**Data Fetching:**

```typescript
function Analytics() {
  const { data: dashboard } = useQuery({
    queryKey: ["analytics", "dashboard"],
    queryFn: () => api.analytics.getDashboard(),
    staleTime: 120_000,
  });

  const { data: scoreDist } = useQuery({
    queryKey: ["analytics", "score-distribution"],
    queryFn: () => api.analytics.getScoreDistribution(),
    staleTime: 300_000,
  });

  return (
    <div>
      <StatCards stats={dashboard?.data} />
      <div className="grid grid-cols-2 gap-6">
        <PropertyByCity data={dashboard?.data.properties.by_city} />
        <ScoreHistogram data={scoreDist?.data} />
        <OutreachFunnel data={dashboard?.data.outreach} />
        <PropertyByType data={dashboard?.data.properties.by_type} />
      </div>
    </div>
  );
}
```

**Charts:**
- Property by City → horizontal bar chart (Recharts)
- Score Distribution → histogram (Recharts)
- Outreach Funnel → funnel chart showing conversion pipeline
- Property by Type → donut chart

---

## 5. API Client Layer

**File:** `frontend/src/api/client.ts`

```typescript
import axios from "axios";

const httpClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "/api/v1",
  headers: { "Content-Type": "application/json" },
});

// Auth interceptor: attach JWT to every request
httpClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor: handle 401 → refresh token flow
httpClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401 && !error.config._retry) {
      error.config._retry = true;
      try {
        const refreshToken = localStorage.getItem("refresh_token");
        const { data } = await axios.post("/api/v1/auth/refresh", {
          refresh_token: refreshToken,
        });
        localStorage.setItem("access_token", data.data.access_token);
        error.config.headers.Authorization = `Bearer ${data.data.access_token}`;
        return httpClient(error.config);
      } catch {
        // Refresh failed → force logout
        localStorage.clear();
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export default httpClient;
```

**File:** `frontend/src/api/types.ts`

```typescript
// Mirrors backend Pydantic schemas

export interface Property {
  id: string;
  canonical_name: string;
  city: string;
  locality: string | null;
  property_type: PropertyType;
  status: PropertyStatus;
  relevance_score: number;
  short_brief: string | null;
  canonical_phone: string | null;
  canonical_email: string | null;
  canonical_website: string | null;
  google_rating: number | null;
  source_count: number;
  contact_count: number;
  has_duplicate_warning: boolean;
  created_at: string;
  thumbnail_url: string | null;
}

export interface PropertyDetail extends Property {
  normalized_address: string | null;
  state: string | null;
  pincode: string | null;
  lat: number;
  lng: number;
  score_breakdown: ScoreBreakdown;
  features: Record<string, any>;
  sources: PropertySource[];
  contacts: PropertyContact[];
  media: PropertyMedia[];
  outreach: OutreachItem | null;
}

export interface PaginatedResponse<T> {
  data: T[];
  meta: {
    total_count: number;
    page_size: number;
    cursor: string | null;
    has_next: boolean;
  };
}

// ... additional types for all API resources
```

**File:** `frontend/src/api/endpoints.ts`

```typescript
import httpClient from "./client";
import type { ... } from "./types";

export const api = {
  properties: {
    list: (params: PropertyFilters) =>
      httpClient.get<PaginatedResponse<Property>>("/properties", { params })
        .then(r => r.data),
    get: (id: string) =>
      httpClient.get<{ data: PropertyDetail }>(`/properties/${id}`)
        .then(r => r.data),
    getChanges: (id: string) =>
      httpClient.get<PaginatedResponse<PropertyChange>>(`/properties/${id}/changes`)
        .then(r => r.data),
    getDuplicates: (id: string) =>
      httpClient.get<{ data: DuplicateCandidate[] }>(`/properties/${id}/duplicates`)
        .then(r => r.data),
    review: (id: string, data: ReviewAction) =>
      httpClient.patch(`/properties/${id}/review`, data)
        .then(r => r.data),
    manualImport: (data: ManualImportData) =>
      httpClient.post("/properties/manual-import", data)
        .then(r => r.data),
    regenerateBrief: (id: string) =>
      httpClient.post(`/properties/${id}/regenerate-brief`)
        .then(r => r.data),
  },

  outreach: {
    list: (params: OutreachFilters) =>
      httpClient.get<PaginatedResponse<OutreachItem>>("/outreach", { params })
        .then(r => r.data),
    update: (id: string, data: OutreachUpdate) =>
      httpClient.patch(`/outreach/${id}`, data)
        .then(r => r.data),
    getStats: (params?: OutreachStatsParams) =>
      httpClient.get("/outreach/stats", { params })
        .then(r => r.data),
  },

  pipeline: {
    getHealth: () =>
      httpClient.get("/pipeline/health").then(r => r.data),
    listRuns: (params?: PipelineRunFilters) =>
      httpClient.get("/pipeline/runs", { params }).then(r => r.data),
    trigger: (data: PipelineTrigger) =>
      httpClient.post("/pipeline/trigger", data).then(r => r.data),
  },

  queries: {
    list: (params?: QueryFilters) =>
      httpClient.get("/queries", { params }).then(r => r.data),
    create: (data: QueryCreate) =>
      httpClient.post("/queries", data).then(r => r.data),
    update: (id: string, data: QueryUpdate) =>
      httpClient.patch(`/queries/${id}`, data).then(r => r.data),
    delete: (id: string) =>
      httpClient.delete(`/queries/${id}`),
  },

  sources: {
    list: () =>
      httpClient.get("/sources").then(r => r.data),
    create: (data: SourceCreate) =>
      httpClient.post("/sources", data).then(r => r.data),
    update: (id: string, data: SourceUpdate) =>
      httpClient.patch(`/sources/${id}`, data).then(r => r.data),
  },

  analytics: {
    getDashboard: () =>
      httpClient.get("/analytics/dashboard").then(r => r.data),
    getScoreDistribution: (params?: ScoreDistParams) =>
      httpClient.get("/analytics/score-distribution", { params }).then(r => r.data),
  },

  auth: {
    login: (data: LoginRequest) =>
      httpClient.post("/auth/login", data).then(r => r.data),
    refresh: (token: string) =>
      httpClient.post("/auth/refresh", { refresh_token: token }).then(r => r.data),
    me: () =>
      httpClient.get("/auth/me").then(r => r.data),
    listUsers: () =>
      httpClient.get("/auth/users").then(r => r.data),
    createUser: (data: UserCreate) =>
      httpClient.post("/auth/users", data).then(r => r.data),
    updateUser: (id: string, data: UserUpdate) =>
      httpClient.patch(`/auth/users/${id}`, data).then(r => r.data),
  },
};
```

---

## 6. Authentication Flow

```typescript
// context/AuthContext.tsx

interface AuthState {
  user: User | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // On mount: check for existing token and load user
  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (token) {
      api.auth.me()
        .then((res) => setUser(res.data))
        .catch(() => localStorage.clear())
        .finally(() => setIsLoading(false));
    } else {
      setIsLoading(false);
    }
  }, []);

  const login = async (email: string, password: string) => {
    const res = await api.auth.login({ email, password });
    localStorage.setItem("access_token", res.data.access_token);
    localStorage.setItem("refresh_token", res.data.refresh_token);
    setUser(res.data.user);
  };

  const logout = () => {
    localStorage.clear();
    setUser(null);
    window.location.href = "/login";
  };

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
```

**Protected Route:**

```typescript
// components/ProtectedRoute.tsx

function ProtectedRoute({
  children,
  allowedRoles,
}: {
  children: React.ReactNode;
  allowedRoles?: UserRole[];
}) {
  const { user, isLoading } = useAuth();

  if (isLoading) return <FullPageSpinner />;
  if (!user) return <Navigate to="/login" />;
  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return <ForbiddenPage />;
  }

  return children;
}
```

---

## 7. TanStack Query Configuration

```typescript
// lib/queryClient.ts

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,          // 30s default — data is fairly fresh
      gcTime: 5 * 60 * 1000,     // 5 min garbage collection
      retry: 1,                   // Single retry on failure
      refetchOnWindowFocus: true, // Refetch when user returns to tab
    },
    mutations: {
      retry: 0,                   // No retry on mutations — user should see error
    },
  },
});
```

**Stale Time Strategy:**

| Query Key | staleTime | Reasoning |
|---|---|---|
| `["properties", filters]` | 30s | Lead queue updates as pipeline runs |
| `["property", id]` | 60s | Detail page — slightly longer cache |
| `["property", id, "duplicates"]` | 5 min | Dedup data changes rarely |
| `["outreach"]` | 15s | Outreach changes frequently during work hours |
| `["pipeline", "health"]` | 30s | Auto-refresh for monitoring |
| `["analytics"]` | 2 min | Dashboard stats — not latency-sensitive |
| `["queries"]` | 60s | Query bank changes rarely |

---

## 8. Frontend Component Library (shadcn/ui)

Components to install from shadcn/ui:

| Component | Used In |
|---|---|
| `Button` | All pages — actions |
| `Badge` | Score badges, status tags, property type tags |
| `Card` | Kanban cards, stat cards, pipeline health |
| `Table` | Lead queue, run history, query bank, sources |
| `Dialog` | Outreach detail, add query, trigger pipeline, merge confirm |
| `Select` | Filters (city, type, status) |
| `Input` | Search, notes, forms |
| `Textarea` | Notes field |
| `Tabs` | Property detail (contacts/sources/media/changes) |
| `Dropdown Menu` | Quick action menus on table rows |
| `Tooltip` | Score breakdown hover, contact confidence |
| `Skeleton` | Loading states for all pages |
| `Toast` (via Sonner) | Success/error notifications |
| `Avatar` | User display in sidebar and assignments |
| `Slider` | Score range filter |

---

## 9. Key Frontend Patterns

### Loading States
Every page has a corresponding `Skeleton` component. No blank screens.

```typescript
if (isLoading) return <LeadQueueSkeleton />;
```

### Error States
Errors from API calls are shown via toast notifications (non-blocking) or inline error states (blocking).

```typescript
// Non-blocking (mutation failed)
toast.error("Failed to approve property: " + error.message);

// Blocking (page failed to load)
if (error) return <ErrorState message="Failed to load property" onRetry={refetch} />;
```

### Empty States
Custom empty states per page with clear call-to-action.

```
No properties found matching your filters.
[Clear Filters] or [Adjust Score Range]
```

### Query Invalidation Strategy

| Action | Invalidate |
|---|---|
| Review a property | `["properties"]`, `["property", id]`, `["analytics"]` |
| Update outreach | `["outreach"]`, `["outreach", "stats"]` |
| Trigger pipeline | `["pipeline"]` |
| CRUD query | `["queries"]` |
| CRUD source | `["sources"]` |

---

*Next Step: Implementation begins → Module-by-module build starting with M1 (Source Registry) + M2 (Query Bank) + DB setup*

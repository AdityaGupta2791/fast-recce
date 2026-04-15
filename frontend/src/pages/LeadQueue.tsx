import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { extractErrorMessage } from "@/api/client";
import { propertiesApi, type PropertyListParams } from "@/api/endpoints";
import type { ReviewAction } from "@/api/types";
import { PageHeader } from "@/components/AppShell";
import { ScoreBadge, StatusBadge } from "@/components/ScoreBadge";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

const CITIES = ["", "Mumbai", "Thane", "Navi Mumbai", "Lonavala", "Pune", "Alibaug", "Alibag", "Chaul", "Varasoli", "Nagaon", "Akshi"];
const STATUSES = ["new", "approved", "rejected", "do_not_contact", "onboarded"];

export function LeadQueuePage() {
  const [filters, setFilters] = useState<PropertyListParams>({
    status: "new",
    sort: "relevance_score_desc",
    offset: 0,
    page_size: PAGE_SIZE,
  });

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["properties", filters],
    queryFn: () => propertiesApi.list(filters),
    placeholderData: (prev) => prev,
  });

  const queryClient = useQueryClient();
  const reviewMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: ReviewAction }) =>
      propertiesApi.review(id, { action }),
    onSuccess: (res) => {
      toast.success(`Marked as ${res.status}`);
      queryClient.invalidateQueries({ queryKey: ["properties"] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
    },
    onError: (err) => {
      toast.error(extractErrorMessage(err));
    },
  });

  function updateFilter<K extends keyof PropertyListParams>(
    key: K,
    value: PropertyListParams[K]
  ) {
    setFilters((prev) => ({ ...prev, [key]: value, offset: 0 }));
  }

  return (
    <div>
      <PageHeader
        title="Lead Queue"
        subtitle={
          data
            ? `${data.meta.total_count} properties matching current filters`
            : "Scored and briefed properties awaiting review"
        }
      />

      <div className="mb-4 flex flex-wrap items-end gap-3 rounded-md border border-border bg-background p-4">
        <FilterSelect
          label="City"
          value={filters.city ?? ""}
          options={CITIES.map((c) => ({ value: c, label: c || "All cities" }))}
          onChange={(v) => updateFilter("city", v || undefined)}
        />
        <FilterSelect
          label="Status"
          value={filters.status ?? "new"}
          options={STATUSES.map((s) => ({ value: s, label: s.replace(/_/g, " ") }))}
          onChange={(v) => updateFilter("status", v)}
        />
        <FilterNumber
          label="Min score"
          value={filters.min_score}
          step={0.05}
          onChange={(v) => updateFilter("min_score", v)}
        />
        <div className="flex-1" />
        <FilterSelect
          label="Sort by"
          value={filters.sort ?? "relevance_score_desc"}
          options={[
            { value: "relevance_score_desc", label: "Score ↓" },
            { value: "relevance_score_asc", label: "Score ↑" },
            { value: "created_at_desc", label: "Newest" },
            { value: "canonical_name_asc", label: "Name A→Z" },
          ]}
          onChange={(v) => updateFilter("sort", v)}
        />
      </div>

      {isLoading && !data ? (
        <SkeletonTable />
      ) : isError ? (
        <ErrorState message={extractErrorMessage(error)} />
      ) : !data || data.data.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="overflow-hidden rounded-md border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Score</th>
                <th className="px-4 py-3">Property</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">City</th>
                <th className="px-4 py-3">Contacts</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.data.map((prop) => (
                <tr
                  key={prop.id}
                  className="border-t border-border transition-colors hover:bg-muted/30"
                >
                  <td className="px-4 py-3">
                    <ScoreBadge score={prop.relevance_score} />
                  </td>
                  <td className="px-4 py-3">
                    <Link
                      to={`/admin/properties/${prop.id}`}
                      className="font-medium hover:underline"
                    >
                      {prop.canonical_name}
                    </Link>
                    {prop.short_brief ? (
                      <div className="mt-0.5 max-w-[48ch] truncate text-xs text-muted-foreground">
                        {prop.short_brief}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {prop.property_type.replace(/_/g, " ")}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {prop.locality ?? prop.city}
                  </td>
                  <td className="px-4 py-3">
                    <ContactIcons prop={prop} />
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={prop.status} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    {prop.status === "new" ? (
                      <div className="inline-flex gap-1">
                        <SmallButton
                          onClick={() =>
                            reviewMutation.mutate({ id: prop.id, action: "approve" })
                          }
                          disabled={reviewMutation.isPending}
                          tone="primary"
                        >
                          Approve
                        </SmallButton>
                        <SmallButton
                          onClick={() =>
                            reviewMutation.mutate({ id: prop.id, action: "reject" })
                          }
                          disabled={reviewMutation.isPending}
                        >
                          Reject
                        </SmallButton>
                      </div>
                    ) : (
                      <Link
                        to={`/admin/properties/${prop.id}`}
                        className="text-xs text-muted-foreground hover:underline"
                      >
                        View
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <Pagination
            total={data.meta.total_count}
            offset={filters.offset ?? 0}
            pageSize={PAGE_SIZE}
            onPageChange={(newOffset) =>
              setFilters((prev) => ({ ...prev, offset: newOffset }))
            }
          />
        </div>
      )}
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function FilterNumber({
  label,
  value,
  step,
  onChange,
}: {
  label: string;
  value: number | undefined;
  step: number;
  onChange: (v: number | undefined) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <input
        type="number"
        step={step}
        min={0}
        max={1}
        placeholder="0.0"
        value={value ?? ""}
        onChange={(e) =>
          onChange(e.target.value === "" ? undefined : Number(e.target.value))
        }
        className="w-24 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
      />
    </label>
  );
}

function ContactIcons({
  prop,
}: {
  prop: { canonical_phone: string | null; canonical_email: string | null; canonical_website: string | null };
}) {
  return (
    <div className="flex gap-1 text-sm">
      <span
        title={prop.canonical_phone ?? "no phone"}
        className={prop.canonical_phone ? "" : "opacity-30"}
      >
        📞
      </span>
      <span
        title={prop.canonical_email ?? "no email"}
        className={prop.canonical_email ? "" : "opacity-30"}
      >
        📧
      </span>
      <span
        title={prop.canonical_website ?? "no website"}
        className={prop.canonical_website ? "" : "opacity-30"}
      >
        🌐
      </span>
    </div>
  );
}

function SmallButton({
  children,
  onClick,
  disabled,
  tone,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  tone?: "primary";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "rounded-md border px-2 py-1 text-xs font-medium transition-colors disabled:opacity-50",
        tone === "primary"
          ? "border-primary bg-primary text-primary-foreground hover:opacity-95"
          : "border-border hover:bg-muted"
      )}
    >
      {children}
    </button>
  );
}

function Pagination({
  total,
  offset,
  pageSize,
  onPageChange,
}: {
  total: number;
  offset: number;
  pageSize: number;
  onPageChange: (offset: number) => void;
}) {
  const from = Math.min(total, offset + 1);
  const to = Math.min(total, offset + pageSize);

  return (
    <div className="flex items-center justify-between border-t border-border bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
      <span>
        Showing {from}–{to} of {total}
      </span>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => onPageChange(Math.max(0, offset - pageSize))}
          disabled={offset === 0}
          className="rounded-md border border-border px-2 py-1 disabled:opacity-50"
        >
          ← Prev
        </button>
        <button
          type="button"
          onClick={() => onPageChange(offset + pageSize)}
          disabled={offset + pageSize >= total}
          className="rounded-md border border-border px-2 py-1 disabled:opacity-50"
        >
          Next →
        </button>
      </div>
    </div>
  );
}

function SkeletonTable() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="h-12 animate-pulse rounded-md bg-muted/40" />
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-md border border-dashed border-border bg-muted/20 p-10 text-center text-sm text-muted-foreground">
      No properties matching current filters.
      <br />
      Try adjusting the status filter or loosening the score range.
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-900 dark:text-red-200">
      Failed to load properties: {message}
    </div>
  );
}

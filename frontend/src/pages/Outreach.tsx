import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { extractErrorMessage } from "@/api/client";
import { outreachApi } from "@/api/endpoints";
import type { OutreachItem, OutreachStatus } from "@/api/types";
import { PageHeader } from "@/components/AppShell";
import { cn } from "@/lib/utils";

const COLUMNS: { status: OutreachStatus; label: string }[] = [
  { status: "pending", label: "Pending" },
  { status: "contacted", label: "Contacted" },
  { status: "responded", label: "Responded" },
  { status: "follow_up", label: "Follow-up" },
  { status: "converted", label: "Converted" },
  { status: "declined", label: "Declined" },
];

// Valid next-step transitions (mirrors OutreachService._TRANSITIONS).
const TRANSITIONS: Record<OutreachStatus, OutreachStatus[]> = {
  pending: ["contacted", "declined"],
  contacted: ["responded", "follow_up", "no_response", "declined"],
  responded: ["follow_up", "converted", "declined"],
  follow_up: ["contacted", "converted", "declined", "no_response"],
  no_response: ["contacted", "follow_up", "declined"],
  converted: [],
  declined: [],
};

export function OutreachPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["outreach"],
    queryFn: () => outreachApi.list({ page_size: 100 }),
  });

  const grouped = useMemo(() => {
    const buckets = new Map<OutreachStatus, OutreachItem[]>();
    for (const col of COLUMNS) buckets.set(col.status, []);
    for (const item of data?.data ?? []) {
      const bucket = buckets.get(item.status as OutreachStatus);
      if (bucket) bucket.push(item);
    }
    return buckets;
  }, [data]);

  const queryClient = useQueryClient();
  const mutate = useMutation({
    mutationFn: ({ id, status }: { id: string; status: OutreachStatus }) =>
      outreachApi.update(id, { status }),
    onSuccess: () => {
      toast.success("Outreach updated");
      queryClient.invalidateQueries({ queryKey: ["outreach"] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
    },
    onError: (err) => toast.error(extractErrorMessage(err)),
  });

  return (
    <div>
      <PageHeader
        title="Outreach Pipeline"
        subtitle={
          data
            ? `${data.meta.total_count} item(s) in the pipeline`
            : "Approved properties ready for outreach"
        }
      />

      {isLoading ? (
        <div className="h-40 animate-pulse rounded-md bg-muted" />
      ) : isError ? (
        <div className="rounded-md border border-red-500/40 bg-red-500/10 p-4 text-sm">
          Failed to load outreach: {extractErrorMessage(error)}
        </div>
      ) : (
        <div className="flex gap-4 overflow-x-auto pb-4">
          {COLUMNS.map((col) => {
            const items = grouped.get(col.status) ?? [];
            return (
              <section
                key={col.status}
                className="flex w-72 shrink-0 flex-col rounded-md border border-border bg-muted/20"
              >
                <header className="flex items-center justify-between border-b border-border px-3 py-2 text-sm">
                  <span className="font-medium capitalize">{col.label}</span>
                  <span className="rounded-md bg-background px-2 py-0.5 text-xs tabular-nums text-muted-foreground">
                    {items.length}
                  </span>
                </header>

                <div className="flex-1 space-y-2 p-2">
                  {items.length === 0 ? (
                    <div className="py-6 text-center text-xs text-muted-foreground">
                      No items
                    </div>
                  ) : (
                    items.map((item) => (
                      <OutreachCard
                        key={item.id}
                        item={item}
                        onTransition={(status) =>
                          mutate.mutate({ id: item.id, status })
                        }
                        disabled={mutate.isPending}
                      />
                    ))
                  )}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

function OutreachCard({
  item,
  onTransition,
  disabled,
}: {
  item: OutreachItem;
  onTransition: (status: OutreachStatus) => void;
  disabled: boolean;
}) {
  const allowed = TRANSITIONS[item.status as OutreachStatus] ?? [];
  return (
    <article className="rounded-md border border-border bg-background p-3 text-sm shadow-sm">
      <Link
        to={`/admin/properties/${item.property.id}`}
        className="block font-medium hover:underline"
      >
        {item.property.canonical_name}
      </Link>
      <div className="mt-0.5 text-xs text-muted-foreground">
        {item.property.city} · {item.property.property_type.replace(/_/g, " ")}
      </div>

      <div className="mt-2 flex items-center gap-2 text-xs">
        <span className="rounded bg-muted px-1.5 py-0.5 tabular-nums">
          pri {item.priority}
        </span>
        <span className="text-muted-foreground">
          {item.contact_attempts} attempt{item.contact_attempts === 1 ? "" : "s"}
        </span>
      </div>

      {item.property.canonical_phone || item.property.canonical_email ? (
        <div className="mt-2 space-y-0.5 text-xs text-muted-foreground">
          {item.property.canonical_phone ? (
            <div>📞 {item.property.canonical_phone}</div>
          ) : null}
          {item.property.canonical_email ? (
            <div className="truncate">📧 {item.property.canonical_email}</div>
          ) : null}
        </div>
      ) : null}

      {allowed.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1">
          {allowed.map((s) => (
            <button
              type="button"
              key={s}
              disabled={disabled}
              onClick={() => onTransition(s)}
              className={cn(
                "rounded-md border border-border px-2 py-1 text-xs transition-colors hover:bg-muted disabled:opacity-50",
                s === "converted"
                  ? "border-green-500/50 text-green-900 hover:bg-green-50 dark:text-green-200"
                  : s === "declined"
                    ? "border-red-500/50 text-red-900 hover:bg-red-50 dark:text-red-200"
                    : ""
              )}
            >
              → {s.replace(/_/g, " ")}
            </button>
          ))}
        </div>
      ) : null}
    </article>
  );
}

import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { extractErrorMessage } from "@/api/client";
import { searchApi } from "@/api/endpoints";
import type { SearchResultItem } from "@/api/types";
import { ScoreBadge } from "@/components/ScoreBadge";

const PROGRESS_STAGES = [
  "Searching Google Places…",
  "Fetching place details…",
  "Crawling property websites…",
  "Extracting contacts and amenities…",
  "Scoring and writing briefs…",
  "Assembling results…",
];

export function SearchResultsPage() {
  const [params] = useSearchParams();
  const query = params.get("q")?.trim() ?? "";

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["search", query],
    queryFn: () =>
      searchApi.search({
        query,
        max_results: 10,
      }),
    enabled: query.length >= 2,
    staleTime: 5 * 60 * 1000,
    retry: 0,
  });

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-6">
        <div className="text-xs text-muted-foreground">Results for</div>
        <h2 className="text-2xl font-semibold">"{query || "—"}"</h2>
      </div>

      {query.length < 2 ? (
        <p className="text-sm text-muted-foreground">
          Enter a search in the top bar to see results.
        </p>
      ) : isLoading ? (
        <LoadingState />
      ) : isError ? (
        <div className="rounded-md border border-red-500/40 bg-red-500/10 p-4 text-sm">
          Search failed: {extractErrorMessage(error)}
        </div>
      ) : !data || data.results.length === 0 ? (
        <EmptyState errors={data?.errors ?? []} />
      ) : (
        <ResultsList
          results={data.results}
          inferredCity={data.inferred_city}
          duration={data.duration_seconds}
          errors={data.errors}
        />
      )}
    </div>
  );
}

function LoadingState() {
  const [stage, setStage] = useState(0);
  useEffect(() => {
    const id = setInterval(() => {
      setStage((s) => Math.min(s + 1, PROGRESS_STAGES.length - 1));
    }, 8000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="space-y-6">
      <div className="rounded-md border border-border bg-background p-6">
        <div className="flex items-center gap-3">
          <div className="h-3 w-3 animate-pulse rounded-full bg-primary" />
          <div className="text-sm font-medium">{PROGRESS_STAGES[stage]}</div>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Live scraping usually takes 30–60 seconds. Hang tight.
        </p>
      </div>
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-24 animate-pulse rounded-md bg-muted/40" />
        ))}
      </div>
    </div>
  );
}

function EmptyState({ errors }: { errors: string[] }) {
  return (
    <div className="rounded-md border border-dashed border-border bg-muted/20 p-10 text-center">
      <p className="text-sm font-medium">No results yet.</p>
      <p className="mt-2 text-xs text-muted-foreground">
        Try a query like <em>"boutique hotels in Lonavala"</em> — include both
        a property type and a city.
      </p>
      {errors.length > 0 ? (
        <details className="mt-4 text-left text-xs text-muted-foreground">
          <summary className="cursor-pointer">Diagnostics</summary>
          <ul className="mt-2 space-y-1">
            {errors.map((e, i) => (
              <li key={i}>• {e}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function ResultsList({
  results,
  inferredCity,
  duration,
  errors,
}: {
  results: SearchResultItem[];
  inferredCity: string | null;
  duration: number;
  errors: string[];
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {results.length} result(s)
          {inferredCity ? <> in <strong>{inferredCity}</strong></> : null}
          · scraped in {duration.toFixed(1)}s
        </span>
        {errors.length > 0 ? (
          <details>
            <summary className="cursor-pointer">
              {errors.length} warning(s)
            </summary>
            <ul className="mt-2 space-y-1">
              {errors.map((e, i) => (
                <li key={i}>• {e}</li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>

      <ul className="space-y-3">
        {results.map((r) => (
          <ResultCard key={r.id} result={r} />
        ))}
      </ul>
    </div>
  );
}

function ResultCard({ result }: { result: SearchResultItem }) {
  return (
    <li className="rounded-md border border-border bg-background p-5 transition-colors hover:border-primary/40">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex items-center gap-2">
            <ScoreBadge score={result.relevance_score} />
            <span className="text-xs uppercase text-muted-foreground">
              {result.property_type.replace(/_/g, " ")}
            </span>
            {result.google_rating ? (
              <span className="text-xs text-muted-foreground">
                ⭐ {result.google_rating}
                {result.google_review_count
                  ? ` (${result.google_review_count})`
                  : ""}
              </span>
            ) : null}
          </div>

          <Link
            to={`/search/property/${result.id}`}
            className="text-lg font-semibold hover:underline"
          >
            {result.canonical_name}
          </Link>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {result.locality ? `${result.locality}, ` : ""}
            {result.city}
          </div>

          {result.short_brief ? (
            <p className="mt-2 line-clamp-3 text-sm leading-relaxed text-muted-foreground">
              {result.short_brief}
            </p>
          ) : null}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-4 text-xs">
        {result.canonical_phone ? (
          <a
            href={`tel:${result.canonical_phone}`}
            className="text-primary hover:underline"
          >
            📞 {result.canonical_phone}
          </a>
        ) : null}
        {result.canonical_email ? (
          <a
            href={`mailto:${result.canonical_email}`}
            className="text-primary hover:underline"
          >
            📧 {result.canonical_email}
          </a>
        ) : null}
        {result.canonical_website ? (
          <a
            href={result.canonical_website}
            target="_blank"
            rel="noreferrer"
            className="text-primary hover:underline"
          >
            🌐 website
          </a>
        ) : null}
      </div>
    </li>
  );
}

import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { extractErrorMessage } from "@/api/client";
import { searchApi } from "@/api/endpoints";
import { ScoreBadge } from "@/components/ScoreBadge";
import {
  ContactList,
  Features,
  ScoreBreakdown,
  SourceLinks,
} from "@/components/PropertyViews";

export function PublicPropertyDetailPage() {
  const { id } = useParams<{ id: string }>();

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["public-property", id],
    queryFn: () => searchApi.getProperty(id!),
    enabled: Boolean(id),
  });

  if (isLoading) {
    return (
      <div className="mx-auto max-w-5xl animate-pulse space-y-4 px-6 py-8">
        <div className="h-8 w-1/3 rounded bg-muted" />
        <div className="h-20 rounded bg-muted" />
        <div className="h-40 rounded bg-muted" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="rounded-md border border-red-500/40 bg-red-500/10 p-6 text-sm text-red-900 dark:text-red-200">
          Failed to load property: {extractErrorMessage(error)}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-4 flex items-center gap-4">
        <Link
          to="/search"
          className="text-xs text-muted-foreground hover:underline"
        >
          ← New search
        </Link>
      </div>

      <header className="mb-6">
        <div className="mb-2 flex items-center gap-3">
          <ScoreBadge score={data.relevance_score} />
          <span className="text-xs uppercase text-muted-foreground">
            {data.property_type.replace(/_/g, " ")}
          </span>
          {data.google_rating ? (
            <span className="text-xs text-muted-foreground">
              Google: ⭐ {data.google_rating}
              {data.google_review_count
                ? ` (${data.google_review_count} reviews)`
                : ""}
            </span>
          ) : null}
        </div>
        <h1 className="text-2xl font-semibold">{data.canonical_name}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {data.locality ? `${data.locality}, ` : ""}
          {data.city}
          {data.state ? `, ${data.state}` : ""}
        </p>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {data.short_brief ? (
            <div className="rounded-md border border-border bg-background p-5">
              <h2 className="mb-2 text-sm font-medium text-muted-foreground">
                Overview
              </h2>
              <p className="leading-relaxed">{data.short_brief}</p>
            </div>
          ) : null}

          {data.score_reason_json ? (
            <ScoreBreakdown reason={data.score_reason_json} />
          ) : null}

          <ContactList contacts={data.contacts} />

          {data.features_json && Object.keys(data.features_json).length > 0 ? (
            <Features features={data.features_json} />
          ) : null}
        </div>

        <div className="space-y-6">
          <SourceLinks
            website={data.canonical_website}
            placeId={data.google_place_id}
            lat={data.lat}
            lng={data.lng}
          />
          <div className="rounded-md border border-border bg-muted/30 p-5 text-xs text-muted-foreground">
            Contact details are scraped from publicly-listed business profiles.
            Please respect property owners when reaching out.
          </div>
        </div>
      </div>
    </div>
  );
}

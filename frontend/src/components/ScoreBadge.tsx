import { cn } from "@/lib/utils";

export function ScoreBadge({ score }: { score: number | null }) {
  if (score === null || score === undefined) {
    return (
      <span className="inline-flex items-center rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
        n/a
      </span>
    );
  }

  const tone =
    score >= 0.7
      ? "bg-green-100 text-green-900 dark:bg-green-900/30 dark:text-green-200"
      : score >= 0.4
        ? "bg-yellow-100 text-yellow-900 dark:bg-yellow-900/30 dark:text-yellow-200"
        : "bg-red-100 text-red-900 dark:bg-red-900/30 dark:text-red-200";

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold tabular-nums",
        tone
      )}
    >
      {score.toFixed(2)}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "new"
      ? "bg-blue-100 text-blue-900 dark:bg-blue-900/30 dark:text-blue-200"
      : status === "approved"
        ? "bg-green-100 text-green-900 dark:bg-green-900/30 dark:text-green-200"
        : status === "rejected"
          ? "bg-red-100 text-red-900 dark:bg-red-900/30 dark:text-red-200"
          : status === "onboarded"
            ? "bg-purple-100 text-purple-900 dark:bg-purple-900/30 dark:text-purple-200"
            : status === "do_not_contact"
              ? "bg-gray-800 text-white"
              : "bg-muted text-foreground";

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium",
        tone
      )}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

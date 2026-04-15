import { useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

/**
 * Minimal shell for the public (no-auth) user flow.
 * Top bar: logo (links to /search) + compact search input + "Admin" link.
 */
export function PublicShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const initialQuery = new URLSearchParams(location.search).get("q") ?? "";
  const [query, setQuery] = useState(initialQuery);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = query.trim();
    if (trimmed.length < 2) return;
    const params = new URLSearchParams();
    params.set("q", trimmed);
    navigate(`/search/results?${params.toString()}`);
  }

  const showCompactSearch = location.pathname.startsWith("/search/results");

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border bg-background">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-6 py-3">
          <Link to="/search" className="shrink-0 text-lg font-semibold">
            FastRecce
          </Link>

          {showCompactSearch ? (
            <form onSubmit={onSubmit} className="flex flex-1 items-center gap-2">
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="e.g. resorts in Alibaug"
                className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-primary"
              />
              <button
                type="submit"
                className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-95"
              >
                Search
              </button>
            </form>
          ) : (
            <div className="flex-1" />
          )}

          <Link
            to="/login"
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            Admin login
          </Link>
        </div>
      </header>

      <main>
        <Outlet />
      </main>
    </div>
  );
}

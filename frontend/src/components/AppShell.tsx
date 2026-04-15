import { NavLink, Outlet } from "react-router-dom";
import type { ReactNode } from "react";

import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/utils";

interface NavItem {
  label: string;
  to: string;
  icon: string;
  adminOnly?: boolean;
}

const NAV: NavItem[] = [
  { label: "Lead Queue", to: "/admin/leads", icon: "📋" },
  { label: "Outreach", to: "/admin/outreach", icon: "📞" },
  { label: "Analytics", to: "/admin/analytics", icon: "📊" },
];

export function AppShell() {
  const { user, logout } = useAuth();

  return (
    <div className="flex h-full min-h-screen bg-background text-foreground">
      <aside className="flex w-64 flex-col border-r border-border bg-muted/30">
        <div className="p-6">
          <h1 className="text-lg font-semibold">FastRecce</h1>
          <p className="text-xs text-muted-foreground">Location acquisition OS</p>
        </div>

        <nav className="flex-1 space-y-1 px-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  isActive
                    ? "bg-primary text-primary-foreground"
                    : "text-foreground hover:bg-muted"
                )
              }
            >
              <span aria-hidden>{item.icon}</span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-border p-4 text-sm">
          <div className="mb-1 truncate font-medium">{user?.full_name}</div>
          <div className="mb-3 text-xs text-muted-foreground">
            {user?.email}
            <br />
            role: <span className="font-mono">{user?.role}</span>
          </div>
          <button
            type="button"
            onClick={logout}
            className="w-full rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted"
          >
            Log out
          </button>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-7xl p-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-6 flex items-start justify-between gap-4">
      <div>
        <h2 className="text-2xl font-semibold">{title}</h2>
        {subtitle ? (
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        ) : null}
      </div>
      {actions ? <div className="flex gap-2">{actions}</div> : null}
    </header>
  );
}

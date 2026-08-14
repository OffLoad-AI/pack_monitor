import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/queue", label: "Review queue" },
  { to: "/products", label: "Products" },
  { to: "/runs", label: "Runs" },
  { to: "/settings", label: "Settings" },
];

export function Layout() {
  const location = useLocation();
  const { data: stats } = useQuery({
    queryKey: ["stats"],
    queryFn: api.stats,
    refetchInterval: 15_000,
  });

  const running = stats?.latest_run?.status === "RUNNING";

  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-ink focus:px-3 focus:py-2 focus:text-sm focus:text-white"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-30 border-b border-line bg-surface">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2">
          <div className="flex items-baseline gap-2">
            <span className="text-sm font-semibold tracking-tight">
              Packaging compliance
            </span>
            <span className="font-mono text-2xs text-ink-4">monitor</span>
          </div>

          <nav className="flex items-center gap-0.5" aria-label="Main">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded px-2.5 py-1 text-sm transition-colors ${
                    isActive
                      ? "bg-surface-sunk font-medium text-ink"
                      : "text-ink-3 hover:bg-surface-sunk hover:text-ink"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-4 text-xs text-ink-3">
            {stats?.awaiting_review ? (
              <NavLink
                to="/queue"
                className="flex items-center gap-1.5 rounded border border-material-line bg-material-bg px-2 py-0.5 font-medium text-material"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-material" />
                {stats.awaiting_review} awaiting review
              </NavLink>
            ) : null}
            {running ? (
              <NavLink
                to={`/runs/${stats!.latest_run!.id}`}
                className="flex items-center gap-1.5 font-mono tabular"
              >
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ink" />
                run {stats!.latest_run!.id} ·{" "}
                {stats!.latest_run!.images_processed}/
                {stats!.latest_run!.images_total}
              </NavLink>
            ) : null}
          </div>
        </div>
      </header>

      <main id="main" key={location.pathname.split("/")[1]}>
        <Outlet />
      </main>
    </div>
  );
}

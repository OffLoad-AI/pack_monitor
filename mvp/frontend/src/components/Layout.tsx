import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

const NAV = [
  { to: "/", label: "Compare", end: true },
  { to: "/history", label: "History", end: false },
  { to: "/settings", label: "Settings", end: false },
];

export function Layout() {
  const health = useQuery({
    queryKey: ["config"],
    queryFn: api.config,
    staleTime: 60_000,
  });

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] items-center gap-6 px-5 py-2.5">
          <span className="text-sm font-semibold tracking-tight text-ink">
            Pairwise packaging comparison
          </span>
          <nav className="flex gap-1" aria-label="Main">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded px-2.5 py-1 text-sm transition-colors ${
                    isActive
                      ? "bg-surface-sunk font-medium text-ink"
                      : "text-ink-3 hover:text-ink"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3 text-2xs text-ink-3">
            {health.data ? (
              <>
                <span title="Which OCR engine is doing the reading">
                  reader{" "}
                  <span className="font-mono text-ink-2">
                    {health.data.ocr_active}
                  </span>
                </span>
                <span
                  className={
                    health.data.calibrated
                      ? "text-ink-3"
                      : "rounded border border-cosmetic-line bg-cosmetic-bg px-1.5 py-0.5 text-cosmetic"
                  }
                  title={
                    health.data.calibrated
                      ? "Thresholds were measured, not chosen."
                      : "A threshold has been edited by hand, so it is no longer purely measured."
                  }
                >
                  {health.data.calibrated ? "calibrated" : "hand-tuned"}
                </span>
              </>
            ) : null}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-5 py-5">
        <Outlet />
      </main>
    </div>
  );
}

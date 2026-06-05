import { useEffect, useState } from "react";
import { Link, NavLink } from "react-router";
import UserIcon from "./user_icon";
import { loadLatestModelRun, type ModelRun } from "~/utils/database";
// Logo — single replaceable import. Swap this one line when the real Tarasque logo lands.
import logo from "~/assets/turtle.svg";

// The three section links. `to` is the section root; NavLink marks the link active for any path
// within that section (e.g. /equity AND /equity/AAPL → Equities; /sector AND /sector/XLK → Sectors).
const NAV_LINKS = [
  { to: "/equity", label: "Equities" },
  { to: "/sector", label: "Sectors" },
  { to: "/macro", label: "Macro" },
];

// LIVE/DEV status. Derived from the Vite dev flag for now — DEV (yellow) on the local dev server
// (`npm run dev`), LIVE (green) otherwise.
// TODO: replace with the planned dev/stg/prod config (app/config.ts) — see backend/CLAUDE.md
// (Environments) — so staging reads LIVE against hosted data without a separate build flag.
const IS_DEV = import.meta.env.DEV;

function HomeIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-5 w-5" aria-hidden="true">
      <path
        d="M3.5 9.5 10 4l6.5 5.5M5.5 8.25V16h9V8.25"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

const longDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });

/**
 * Slim, sticky, scroll-locked top navbar. Renders only under ProtectedLayout. Three zones:
 *  - Left:  home + divider + logo/title (the whole span → /dashboard) then the section links.
 *  - Right: version status pill · "Last refresh" date · profile menu.
 *
 * Version + last-refresh come from the latest model_runs row (loadLatestModelRun, non-fatal —
 * null renders a placeholder). Status (LIVE/DEV) comes from the env flag above.
 */
export default function Navbar() {
  const [modelRun, setModelRun] = useState<ModelRun | null>(null);

  useEffect(() => {
    loadLatestModelRun().then(setModelRun);
  }, []);

  // Two fully-static class strings per slot so Tailwind's JIT can see them (it can't detect
  // class names assembled at runtime). Selected by env.
  const statusPill = IS_DEV
    ? "border-(--status-dev-border) bg-(--status-dev-bg)"
    : "border-(--status-live-border) bg-(--status-live-bg)";
  const statusDot = IS_DEV ? "bg-(--status-dev)" : "bg-(--status-live)";
  const statusText = IS_DEV ? "text-(--status-dev)" : "text-(--status-live)";
  const statusLabel = IS_DEV ? "DEV" : "LIVE";

  return (
    <header className="navbar">
      <div className="flex h-14 items-center justify-between gap-4 px-4">
        {/* ── Left zone ── */}
        <div className="flex min-w-0 items-center gap-1">
          {/* Home → divider → logo/title: one clickable span → /dashboard. */}
          <Link
            to="/dashboard"
            aria-label="Go to dashboard"
            className="flex items-center gap-3 rounded-md py-1 pr-2 pl-1 text-(--text-secondary) hover:text-(--text-primary)"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-md hover:bg-(--track-bg)">
              <HomeIcon />
            </span>
            <span className="h-6 w-px bg-(--panel-border)" aria-hidden="true" />
            <img src={logo} alt="" aria-hidden="true" className="h-7 w-7 shrink-0" />
            <span className="flex items-baseline gap-1.5 leading-none whitespace-nowrap">
              <span className="text-base font-bold tracking-tight text-(--text-primary)">
                Tarasque
              </span>
              <span className="font-mono text-[10px] font-medium tracking-[0.18em] text-(--text-muted) uppercase">
                Risk &amp; Analytics
              </span>
            </span>
          </Link>

          {/* Small gap, then the section links. */}
          <nav className="ml-3 flex items-center gap-1">
            {NAV_LINKS.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm font-bold transition-colors ${
                    isActive
                      ? "bg-(--track-bg) text-(--text-primary)"
                      : "text-(--text-secondary) hover:bg-(--track-bg) hover:text-(--text-primary)"
                  }`
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
        </div>

        {/* ── Right zone ── */}
        <div className="flex shrink-0 items-center gap-3">
          {/* Version + status pill — "<model_version> · LIVE|DEV". */}
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${statusPill}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${statusDot}`} aria-hidden="true" />
            {modelRun?.model_version && (
              <>
                <span className="text-(--text-secondary)">{modelRun.model_version}</span>
                <span className="text-(--text-muted)">·</span>
              </>
            )}
            <span className={statusText}>{statusLabel}</span>
          </span>

          {/* Last refresh — latest model_runs.run_date (NOT live time). */}
          <span className="hidden text-xs text-(--text-muted) md:inline">
            Last refresh {modelRun?.run_date ? longDate(modelRun.run_date) : "—"}
          </span>

          <UserIcon />
        </div>
      </div>
    </header>
  );
}

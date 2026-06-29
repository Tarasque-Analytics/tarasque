import type { ReactNode } from "react";

// Shared structural primitives for page section components (equity, macro, …). Every section
// renders inside a <Card> and uses <Empty> for its loading / no-data / unavailable placeholder, so
// the panels stay structurally uniform across pages. These are deliberately the *standard* — new
// sections should reuse them rather than re-declaring their own. See app/CLAUDE.md ("Equity section
// components — shared structure" and "Macro page").

/** Card surface every section panel sits in (.panel + standard padding). */
export function Card({ children }: { children: ReactNode }) {
  return <div className="panel p-5">{children}</div>;
}

/** Centered, muted placeholder for a section's loading / empty / unavailable state. */
export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-80 items-center justify-center text-sm text-(--text-secondary)">
      {children}
    </div>
  );
}

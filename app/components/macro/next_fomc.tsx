import { Card } from "~/components/ui/section";

// NEXT FOMC card for /macro (#134). Small standalone card in the top band: days-to-meeting, the
// meeting date, the market-implied rate move, and the implied year-end path.
//
// Scaffolding only — every value below is a static placeholder to convey layout, NOT live data.
// TODO(#134): wire real data. Days-till-FOMC already exists backend-side (macro_calendar); the
// rate-move odds are still undecided — the issue proposes the frontend pulling them directly from
// Polymarket/Kalshi, which crosses the browser→external-service boundary (decision deferred; see
// backend/CLAUDE.md). Keep these literals obviously static until then.
const PLACEHOLDER = {
  days: "27d",
  date: "Mar 18, 2026",
  move: "35 bp cut · 62%",
  impliedPath: "Implied path: -68 bp by year-end.",
};

export default function NextFomc() {
  return (
    <Card>
      <Header />
      <div className="mt-3">
        <div className="flex items-baseline gap-2">
          <span className="text-4xl font-bold tracking-tight text-(--text-primary)">
            {PLACEHOLDER.days}
          </span>
          <span className="text-sm text-(--text-muted)">{PLACEHOLDER.date}</span>
        </div>
        <span className="badge badge-neutral mt-3">{PLACEHOLDER.move}</span>
        <p className="mt-2 text-sm text-(--text-secondary)">{PLACEHOLDER.impliedPath}</p>
      </div>
    </Card>
  );
}

/* ── header: small uppercase eyebrow label ── */
function Header() {
  return (
    <h2 className="text-xs font-semibold tracking-wide text-(--text-muted) uppercase">NEXT FOMC</h2>
  );
}

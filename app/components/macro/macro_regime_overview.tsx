import { Card } from "~/components/ui/section";

// Macro regime overview banner for /macro (#135). Full-width heading above the regime scatter:
// the corpus subtitle, a regime badge, an "as of" timestamp, and right-aligned VRP wedge stat chips
// (size + percentile). Mostly a heading — it sizes a percentile from a current average value.
//
// Scaffolding only — the regime label, timestamp, and wedge figures are static placeholders.
// TODO(#135): wire real data. The VRP wedge size (pp) and its percentile originate from the
// off-repo quant model → Supabase → backend (read-only); see backend/CLAUDE.md. Per the issue, the
// mockup's dispersion-σ figure and "VOL REGIME" chip are intentionally omitted.
const PLACEHOLDER = {
  corpus: "S&P large-cap corpus · NN names",
  regime: "Mid-cycle · widening dispersion",
  asOf: "as of — ET",
  wedge: "+4.6 pp",
  wedgePctile: "68th",
};

export default function MacroRegimeOverview() {
  return (
    <Card>
      <Header />
    </Card>
  );
}

/* ── header: title · regime badge · corpus + as-of · right-aligned wedge stat chips ── */
function Header() {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <div className="flex flex-wrap items-center gap-x-2">
          <h2 className="text-2xl font-bold tracking-tight text-(--text-primary)">
            Macro · Cross-section regime
          </h2>
          <span className="badge badge-neutral">{PLACEHOLDER.regime}</span>
        </div>
        <p className="mt-0.5 text-sm text-(--text-muted)">{PLACEHOLDER.corpus}</p>
        <p className="mt-0.5 text-xs text-(--text-muted)">{PLACEHOLDER.asOf}</p>
      </div>
      <div className="flex items-start gap-6">
        <Stat label="WEDGE" value={PLACEHOLDER.wedge} positive />
        <Stat label="WEDGE %ILE" value={PLACEHOLDER.wedgePctile} />
      </div>
    </div>
  );
}

/* ── one labeled stat chip (uppercase eyebrow over a bold value) ── */
function Stat({ label, value, positive }: { label: string; value: string; positive?: boolean }) {
  return (
    <div className="text-right">
      <div className="text-xs font-semibold tracking-wide text-(--text-muted) uppercase">
        {label}
      </div>
      <div className={`text-xl font-bold ${positive ? "text-(--pos)" : "text-(--text-primary)"}`}>
        {value}
      </div>
    </div>
  );
}

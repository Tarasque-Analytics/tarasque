import { constructGicsCode } from "~/utils/gics";
import { useEquityData } from "~/context/EquityDataContext";

function formatMarketCap(marketCap: number | null | undefined): string {
  if (!marketCap) return "—";
  const b = marketCap / 1e9;
  if (b >= 200) return `Mega-cap ($${b.toFixed(1)}B)`;
  if (b >= 10) return `Large-cap ($${b.toFixed(0)}B)`;
  if (b >= 2) return `Mid-cap ($${b.toFixed(1)}B)`;
  if (b >= 0.3) return `Small-cap ($${(b * 1000).toFixed(0)}M)`;
  return `Micro-cap ($${(b * 1000).toFixed(0)}M)`;
}

function DataRow({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div className="data-row">
      <span className="data-row-label">{label}</span>
      <span className="data-row-value">{value ?? "N/A"}</span>
    </div>
  );
}

export default function EquityMetaData() {
  const payload = useEquityData();

  // Early return if payload is null
  if (!payload) {
    return null;
  }

  const security = payload.security;
  const next_dividend = payload.volatility_history?.[0]?.next_dividend_date;
  const next_earnings = payload.volatility_history?.[0]?.next_earnings_date;

  if (!security) {
    return null;
  }

  // Plain const, not useMemo — constructGicsCode is a cheap synchronous lookup, and a hook here
  // would run after the early returns above, violating the Rules of Hooks.
  const gicsCode = constructGicsCode(
    security.gics_sector,
    null,
    security.gics_industry,
    security.gics_subindustry,
  );
  const sector = security?.gics_sector;
  const industry = security?.gics_industry;
  const subindustry = security?.gics_subindustry;
  // Known data gaps — kept null until sourced (rendered as the unavailable marker, never faked):
  //   - beta / market_cap: not columns in `securities` (#104)
  //   - avg_spread + model outputs (z_score_stabilized, tail_risk_95): not yet in the DB (#70)
  // Do not wire these to any backend/payload field until the data actually exists.
  const marketCap = null as number | null;
  const beta = null as number | null;
  const avg_spread = null as number | null;
  return (
    <div className="equity-classes-container panel p-5">
      {/* Equity Classes */}
      <div>
        <h3 className="equity-section-title">Equity Classes</h3>
        <div className="equity-section">
          <DataRow label="Sector" value={sector} />
          <DataRow label="Sub-sector" value={subindustry || industry} />
          <DataRow label="Market cap" value={marketCap ? formatMarketCap(marketCap) : null} />
          <DataRow label="GICS" value={gicsCode} />
        </div>
      </div>

      {/* Reference — always rendered; `security` is guaranteed non-null past the early returns */}
      <div className="equity-reference-section">
        <h3 className="equity-section-title">Reference</h3>
        <div className="equity-section">
          <DataRow label="Beta (3y)" value={beta != null ? beta.toFixed(2) : null} />
          <DataRow
            label="Avg spread"
            value={avg_spread != null ? avg_spread.toFixed(2) + "%" : null}
          />
          <DataRow label="Next earnings" value={next_earnings ?? null} />
          <DataRow label="Next dividend" value={next_dividend ?? null} />
        </div>
      </div>
    </div>
  );
}

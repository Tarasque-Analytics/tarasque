import type { EquitiesPayload } from "~/utils/database";
import {getBeta, getMarketCap, getAvgSpread} from "~/utils/database"
import {constructGicsCode} from "~/utils/gics"
import { useEquityData } from "~/context/EquityDataContext";
import { useMemo } from "react";


function formatMarketCap(marketCap: number | null | undefined): string {
  if (!marketCap) return "—";
  const b = marketCap / 1e9;
  if (b >= 200) return `Mega-cap ($${(b).toFixed(1)}B)`;
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

export default function EquityClasses() {
  const payload = useEquityData()
    
  // Early return if payload is null
  if (!payload) {
    return null;
  }

  const security = payload.security
  const next_dividend = payload.volatility_history?.[0]?.next_dividend_date
  const next_earnings = payload.volatility_history?.[0]?.next_earnings_date
  

  if (!security) {
    return null;
  }

  // TODO: Replace this when we actually figure out how we're getting the GICS code
  const gicsCode = useMemo(
    () => constructGicsCode(security.gics_sector, null, security.gics_industry, security.gics_subindustry),
    [security.gics_sector, security.gics_industry, security.gics_subindustry]
  );
  // console.log("GICS CODE: " + gicsCode)
  const sector = security?.gics_sector;
  const industry = security?.gics_industry;
  const subindustry = security?.gics_subindustry;
  // TODO: Replace this when we actually figure out how we're getting the market cap
  const marketCap = useMemo(() => getMarketCap(security.ticker), [security.ticker]);
  // TODO: Replace this when we actually figure out how we're getting the 3 yr beta
  const beta = useMemo(() => getBeta(security.ticker), [security.ticker]);
  const avg_spread = useMemo(() => getAvgSpread(security.ticker), [security.ticker])
  return (
    <div className="equity-classes-container">
      {/* Equity Classes */}
      <div>
        <h3 className="equity-section-title">
          Equity Classes
        </h3>
        <div className="equity-section">
          <DataRow label="Sector" value={sector} />
          <DataRow label="Sub-sector" value={subindustry || industry} />
          <DataRow label="Market cap" value={marketCap ? formatMarketCap(marketCap) : null} />
          <DataRow label="GICS" value={gicsCode} />
        </div>
      </div>

      {/* Reference */}
      {(beta != null || next_earnings || next_dividend || avg_spread) && (
        <div className="equity-reference-section">
          <h3 className="equity-section-title">
            Reference
          </h3>
          <div className="equity-section">
            <DataRow label="Beta (3y)" value={beta != null ? beta.toFixed(2) : null} />
            <DataRow label="Avg spread" value={avg_spread != null ? avg_spread.toFixed(2) + "%" : null} />
            <DataRow label="Next earnings" value={next_earnings ?? null} />
            <DataRow label="Next dividend" value={next_dividend ?? null} />
          </div>
        </div>
      )}
    </div>
  );
}

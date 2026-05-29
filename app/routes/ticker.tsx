import type { TickerDataPayload } from "../context/TickerDataContext";
import type { LoaderFunctionArgs } from "react-router";
import { loadTickerPayload } from "../utils/tickers";
import { loadEquityData, type EquitiesPayload } from "../utils/database";
import TickerView from "../pages/Ticker";

export interface TickerLoaderData {
  // Legacy file-backed payload consumed by the existing ticker components.
  payload: TickerDataPayload;
  // Database-backed payload from GET /api/equity/:symbol; null if the DB query is unavailable.
  equity: EquitiesPayload | null;
}

// Route loader: fetch both the file payload (required) and the DB equity payload (optional)
// in parallel so navigating to /equity/:symbol hits /api/equity/:symbol with the real symbol.
export async function loader({ params }: LoaderFunctionArgs): Promise<TickerLoaderData> {
  const { symbol } = params;

  if (!symbol) {
    throw new Response("Symbol parameter is required", { status: 400 });
  }

  const [payloadResult, equityResult] = await Promise.allSettled([
    loadTickerPayload(symbol),
    loadEquityData(symbol),
  ]);

  if (payloadResult.status === "rejected") {
    const reason = payloadResult.reason;
    throw new Response(
      `Failed to load data for ${symbol}: ${reason instanceof Error ? reason.message : "Unknown error"}`,
      { status: 404 }
    );
  }

  // DB payload is non-fatal: keep rendering from the file payload if /api/equity fails.
  let equity: EquitiesPayload | null = null;
  if (equityResult.status === "fulfilled") {
    equity = equityResult.value;
  } else {
    console.error(`Equity data unavailable for ${symbol}:`, equityResult.reason);
  }

  return { payload: payloadResult.value, equity };
}

// For parsing payload JSON file:
// meta:
  // data goes in attributes (top left)
  // tail_risk_95: stop-loss
// hedging:
// explainability:
  // pie chart (top right)
// charts:
  // monte_carlo:
    // graph this: three-column data (p95, mean, p05)
    // use steps length for x-axis (bottom left)
// opportunities:
  // symbol: r"[A-Z]{4} \d{6} (C|P) \d{5}\d{3}"
  //          Ticker   YYMMDD Call/Put Strike $xxxxx.xxx
  // "type": call | put
  // "strike": option strike price
  // "expiry": option expiry date (YYYY-MM-DD)
  // "mkt_px": market price
  // "model_px": model price
  // "edge_pct": difference between model price and market price as a percentage of market price
  // "spread_pct": spread in price between bid and ask for this contract
  // "liquidity": HIGH | MEDIUM | LOW - if LOW, deprioritize this opportunity
  // "action": recommended action based on metric
  // "iv": implied volatility
  // "fair_vol": model estimate of volatility
  // "z_score": (model volatility - market volatility) / (RMSE * (1 - 21dayvelocity))

  // (center bottom)
  // if liquidity != LOW and market "iv" != null: rank by z-score

export default TickerView;

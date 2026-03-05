import type { TickerDataPayload } from "../context/TickerDataContext";
import type { LoaderFunctionArgs } from "react-router";
import TickerView from "../pages/Ticker";

// Glob all Payload JSON files in the data directory
const payloadModules = import.meta.glob('../assets/data/*_Payload.json');

// Route loader: dynamically fetch ${symbol}_Payload.json based on URL parameter
export async function loader({ params }: LoaderFunctionArgs): Promise<TickerDataPayload> {
  const { symbol } = params;
  
  if (!symbol) {
    throw new Response("Symbol parameter is required", { status: 400 });
  }
  
  // Construct the module path
  const modulePath = `../assets/data/${symbol}_Payload.json`;
  
  // Check if the module exists
  if (!(modulePath in payloadModules)) {
    throw new Response(`No data found for symbol: ${symbol}`, { status: 404 });
  }
  
  // Dynamically import the module
  const module = await payloadModules[modulePath]() as { default: TickerDataPayload };
  
  return module.default || module;
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

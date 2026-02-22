// # centrally, we show the ticker "price arbitrage map" - for this we will need concurrent data from a new run, i also want hover over functionability to show off the specific call price and strike price
// # on the bottom i want to show the top ten predictors by a metric of Prob. of profit and getEnabledCategorie
import { useTickerData } from '~/context/TickerDataContext';
import Placeholder from '../ui/placeholder';

// From routes/ticker.tsx
// opportunities:
  // symbol: r"[A-Z]{4} \d{6} (C|P) \d{5}\d{3}"
  //          Ticker   YYMMDD Call/Put Strike $xxxxx.xxx
  // "type": call | put, string
  // "strike": option strike price, number
  // "expiry": option expiry date (YYYY-MM-DD), string
  // "mkt_px": market price, number
  // "model_px": model price, number
  // "edge_pct": difference between model price and market price as a percentage of market price, number
  // "spread_pct": spread in price between bid and ask for this contract, number
  // "liquidity": HIGH | MEDIUM | LOW - if LOW, deprioritize this opportunity, string
  // "action": recommended action based on metric, string
  // "iv": implied volatility, number | null
  // "fair_vol": model estimate of volatility, number
  // "z_score": (model volatility - market volatility) / (RMSE * (1 - 21dayvelocity)), number | null

// From TickerDataContext.tsx
// opportunities: data.opportunities || [],

  // "opportunities": [
  //     {
  //         "symbol": "MS260220C00205000",
  //         "type": "call",
  //         "strike": 205.0,
  //         "expiry": "2026-02-20",
  //         "mkt_px": 0.05,
  //         "model_px": 0.0,
  //         "edge_pct": 100.0,
  //         "spread_pct": 100.0,
  //         "liquidity": "LOW",
  //         "action": "PASS_Liquidity",
  //         "iv": null,
  //         "fair_vol": 0.01,
  //         "z_score": null
  //     },

export default function Options() {
  const { opportunities } = useTickerData();
  if (!opportunities || opportunities.length === 0) {
    return (
      <div>
        <Placeholder title="Something went wrong" />
      </div>
    );
  }

  return (
    <div>
      <Placeholder title="Options" />
    </div>
  );
}
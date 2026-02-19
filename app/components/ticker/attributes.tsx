import { useTickerData } from "~/context/TickerDataContext";
import Placeholder from "../ui/placeholder";

export default function Attributes() {
  const { meta } = useTickerData();

  //   "meta": {
  //     "ticker": "MS",
  //     "timestamp": "2026-02-16 10:49",
  //     "spot_price": 171.15,
  //     "forecast_rv": {
  //         "21": 0.1893,
  //         "63": 0.2078,
  //         "126": 0.212
  //     },
  //     "garch_21d": 0.2995,
  //     "market_iv_atm": 0.368,
  //     "vrp_wedge": 0.1511,
  //     "z_score_stabilized": 3.81,
  //     "tail_risk_95": 156.38
  // },

  return (
    <div className="flex flex-col gap-2">
      <text>Attributes</text>
      <text>Z-score: {meta.z_score_stabilized}</text>
      <text>21-day RV: {meta.forecast_rv["21"]}</text>
      <text>63-day RV: {meta.forecast_rv["63"]}</text>
      <text>126-day RV: {meta.forecast_rv["126"]}</text>
      <text>Stop-loss: {meta.tail_risk_95}</text>
      <text>YTD Returns: N/A</text>
      <text>Next Earnings Date: YYYY/MM/DD</text>
      <text>VRP: {meta.vrp_wedge}</text>
    </div>
  );
}

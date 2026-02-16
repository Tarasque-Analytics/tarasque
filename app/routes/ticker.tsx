import type { TickerDataPayload } from "../context/TickerDataContext";
import TickerView from "../pages/Ticker";

// Route loader: fetch MS_Payload.json
// export async function loader(): Promise<TickerDataPayload> {
//   const payload = await import("../assets/data/MS_Payload.json");
//   return payload.default || payload;
// }

import payload from "../assets/data/MS_Payload.json";

export async function loader(): Promise<TickerDataPayload> {
  return payload;
}

export default TickerView;

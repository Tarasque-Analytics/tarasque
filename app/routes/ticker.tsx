import type { LoaderFunctionArgs } from "react-router";
import { loadEquityData, type EquitiesPayload } from "../utils/database";
import TickerView from "../pages/Ticker";

export interface TickerLoaderData {
  // Database-backed payload from GET /api/equity/:symbol; null if the DB query is unavailable.
  // The page renders an explicit "unavailable" state when this is null.
  equity: EquitiesPayload | null;
}

// Route loader: fetch the DB equity payload for /equity/:symbol. The fetch is non-fatal — on
// failure we return null so the page can render an explicit error state rather than throwing.
export async function loader({ params }: LoaderFunctionArgs): Promise<TickerLoaderData> {
  const { symbol } = params;

  if (!symbol) {
    throw new Response("Symbol parameter is required", { status: 400 });
  }

  let equity: EquitiesPayload | null = null;
  try {
    equity = await loadEquityData(symbol);
  } catch (error) {
    if (import.meta.env.DEV) {
      console.error(`Equity data unavailable for ${symbol}:`, error);
    } else {
      console.error(`Equity data unavailable for ${symbol}`);
    }
  }

  return { equity };
}

export default TickerView;

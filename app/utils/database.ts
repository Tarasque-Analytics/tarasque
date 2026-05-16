/**
 * Includes definitions for rows stored in the various tables in the database along
 * with functions to gather comprehensive data for any one of the pages
 * 
 */


const API_BASE_URL = "http://localhost:8000/api";
// Volatility and forecasting data
export interface VolatilityRecord {
  date: string;
  rv: number;
  ewma_vol: number;
  iv_atm_30d: number;
  iv_atm_60d: number;
  iv_atm_91d: number;
  iv_atm_182d: number;
  vrp_wedge: number;
  vrp_wedge_ewma_21d: number;
  pfv_21: number;
  pfv_63: number;
  pfv_126: number;
  pfv_q15_21: number;
  pfv_q15_63: number;
  pfv_q15_126: number;
  pfv_cal_21: number;
  pfv_cal_63: number;
  pfv_cal_126: number;
  next_earnings_date?: string;
  days_to_earnings?: number;
  next_dividend_date?: string;
  days_to_dividend?: number;
  model_run_id: number;
}

// Price history (OHLCV)
export interface PriceRecord {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  adj_close: number;
  volume: number;
}

// Options chain
export interface OptionRecord {
  id: number;
  security_id: number;
  snapshot_date: string;
  expiry: string;
  strike: number;
  option_type: "C" | "P";
  bid: number;
  ask: number;
  mid: number;
  last: number;
  volume: number;
  open_interest: number;
  iv: number;
  delta: number;
}

// AI overview
export interface AIOverview {
  id: number;
  security_id: number;
  date: string;
  model_version: string;
  prompt_version: string;
  headline: string;
  risk_tier: string;
  content: Record<string, unknown>;
  input_tokens: number;
  output_tokens: number;
  generated_at: string;
}

// SHAP snapshot
export interface SHAPSnapshot {
  security_id: number;
  retrain_date: string;
  horizon: number;
  snapshot_date: string;
  base_value: number;
  predicted_value: number;
  feature_data: Record<string, unknown>;
}

// Distribution data
export interface DistributionBin {
  scope: "stock" | "sector" | "market";
  bin_low: number;
  bin_high: number;
  count: number;
  current_value: number;
  current_percentile: number;
}

// Event
export interface Event {
  id: number;
  event_date: string;
  event_type: "earnings" | "dividend" | "fomc";
  severity: "crisis" | "major" | "notable";
  scope: "market" | "sector" | "ticker";
  scope_value?: string;
  title: string;
  description?: string;
  source?: string;
}

// Complete equity payload
export interface EquitiesPayload {
  symbol: string;
  volatility_history: VolatilityRecord[];
  price_history: PriceRecord[];
  options_chain: OptionRecord[];
  ai_overview: AIOverview | null;
  latest_shap_snapshot: SHAPSnapshot[];
  distribution_data: DistributionBin[];
  events: Event[];
}

/**
 * Load comprehensive equity data for a specific ticker from the backend
 * Includes volatility, price history, options, AI overview, SHAP, distributions, and events
 * Used for /equity/:symbol
 */
export async function loadEquityData(symbol: string): Promise<EquitiesPayload> {
  try {
    const response = await fetch(`${API_BASE_URL}/equity/${symbol}`);
    console.log("response: " + response);
    if (!response.ok) {
      if (response.status === 404) {
        throw new Error(`No equity data found for symbol: ${symbol}`);
      }
      throw new Error(`Failed to fetch equity data for ${symbol}: ${response.statusText}`);
    }
    return await response.json();
  } catch (error) {
    console.error(`Error loading equity data for ${symbol}:`, error);
    throw error;
  }
}
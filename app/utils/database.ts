/**
 * Canonical client-side spec for the database-backed API.
 *
 * Row interfaces mirror the Supabase tables (see supabase/database_SQL_defs.sql), and
 * loadEquityData() fetches the composite payload for the /equity/:symbol page from
 * GET /api/equity/:symbol. Numeric columns that are nullable in the DB are typed `| null`.
 */

import type { LargeNumberLike } from "crypto";

const API_BASE_URL = "http://localhost:8000/api";

// Volatility and forecasting data (volatility_history)
export interface VolatilityRecord {
  date: string;
  rv: number | null;
  ewma_vol: number | null;
  iv_atm_30d: number | null;
  iv_atm_60d: number | null;
  iv_atm_91d: number | null;
  iv_atm_182d: number | null;
  vrp_wedge: number | null;
  vrp_wedge_ewma_21d: number | null;
  pfv_21: number | null;
  pfv_63: number | null;
  pfv_126: number | null;
  pfv_q15_21: number | null;
  pfv_q15_63: number | null;
  pfv_q15_126: number | null;
  pfv_cal_21: number | null;
  pfv_cal_63: number | null;
  pfv_cal_126: number | null;
  next_earnings_date?: string | null;
  days_to_earnings?: number | null;
  next_dividend_date?: string | null;
  days_to_dividend?: number | null;
  model_run_id: number | null;
}

// Security metadata (securities) — subset returned alongside the equity payload for page chrome
// (company name + sector/industry badges). The backend already loads the full row to resolve
// security_id; these fields are surfaced for the UI.
export interface SecurityMeta {
  security_id: number;
  ticker: string;
  company_name: string | null;
  gics_sector: string | null;
  gics_industry: string | null;
  gics_subindustry: string | null;
  sector_etf: string | null;
}

// Price history / OHLCV (prices_history)
export interface PriceRecord {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  adj_close: number | null;
  volume: number | null;
}

// Options chain (options_chain)
export interface OptionRecord {
  id: number;
  security_id: number;
  snapshot_date: string;
  expiry: string;
  strike: number;
  option_type: "C" | "P";
  bid: number | null;
  ask: number | null;
  mid: number | null;
  last: number | null;
  volume: number | null;
  open_interest: number | null;
  iv: number | null;
  delta: number | null;
}

// AI overview (ai_overview) — backend returns select("*")
export interface AIOverview {
  id: number;
  security_id: number;
  model_ver: string;
  prompt_ver: string;
  headline: string;
  content: Record<string, unknown>;
  generated_at: string;
  flagged: boolean | null;
}

// SHAP snapshot (shap_snapshot)
export interface SHAPSnapshot {
  security_id: number;
  retrain_date: string;
  horizon: number;
  snapshot_date: string;
  base_value: number | null;
  predicted_value: number | null;
  feature_data: Record<string, unknown>;
}

// Distribution data.
// NOTE: not currently returned by the API — the get_distribution RPC is disabled pending
// finance input (tracked in the distribution PR). Kept here for when it's re-enabled.
export interface DistributionBin {
  scope: "stock" | "sector" | "market";
  bin_low: number;
  bin_high: number;
  count: number;
  current_value: number;
  current_percentile: number;
}

// Event (event_history) — per-security only. Market-wide events (CPI/FOMC/NFP) live in
// macro_calendar, not here, so there is no market/sector scope or severity.
export interface EventRecord {
  security_id: number;
  event_id: number;
  event_date: string;
  title: string;
  description?: string | null;
  event_type?: string | null;
  scope?: string | null;
  source?: string | null;
}

// Latest model run — feeds the navbar version pill + "Last refresh" date (GET /api/model-runs/latest)
export interface ModelRun {
  model_version: string | null;
  run_date: string | null;
}

// Complete payload from GET /api/equity/:symbol
export interface EquitiesPayload {
  symbol: string;
  // Security metadata for the page header (company name, sector/industry). Present whenever the
  // payload is (the backend resolves the security before aggregating); optional for resilience.
  security?: SecurityMeta;
  volatility_history: VolatilityRecord[];
  price_history: PriceRecord[];
  options_chain: OptionRecord[];
  ai_overview: AIOverview | null;
  latest_shap_snapshot: SHAPSnapshot[];
  // Disabled in the backend (get_distribution) — omitted from the payload for now.
  distribution_data?: DistributionBin[];
  events: EventRecord[];
}

/**
 * Load comprehensive equity data for a ticker from the database-backed API.
 * Includes volatility, price history, options, AI overview, SHAP, and events.
 * Used for /equity/:symbol.
 */
export async function loadEquityData(symbol: string): Promise<EquitiesPayload> {
  try {
    const response = await fetch(`${API_BASE_URL}/equity/${symbol}`);
    if (!response.ok) {
      if (response.status === 404) {
        throw new Error(`No equity data found for symbol: ${symbol}`);
      }
      throw new Error(`Failed to fetch equity data for ${symbol}: ${response.statusText}`);
    }
    return await response.json();
  } catch (error) {
    if (import.meta.env.DEV) {
      console.error(`Error loading equity data for ${symbol}:`, error);
    } else {
      console.error(`Error loading equity data for ${symbol}`);
    }
    throw error;
  }
}

/**
 * Load the latest model run for the navbar (version + run date).
 * Non-fatal: returns null on any failure so the navbar can render a placeholder instead of
 * breaking (consistent with how the equity components handle missing data).
 */
export async function loadLatestModelRun(): Promise<ModelRun | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/model-runs/latest`);
    if (!response.ok) return null;
    return (await response.json()) as ModelRun;
  } catch (error) {
    if (import.meta.env.DEV) {
      console.error("Error loading latest model run:", error);
    } else {
      console.error("Error loading latest model run");
    }
    return null;
  }
}

//These functions may, in the endm not be necessary as we could potentially just package the same
// information inside the equities payload

// TODO: PROVIDE ACTUAL IMPLEMENTATION WHEN WE KNOW WHERE BETA IS COMING FROM
export function getBeta(symbol: string): number {
  return Math.random() * 3;
}

// TODO: PROVIDE ACTUAL IMPLEMENTATION WHEN WE KNOW WHERE MARKET CAP IS COMING FROM
export function getMarketCap(symbol: string): number {
  return Math.random() * 1000000000000;
}

// TODO: PROVIDE ACTUAL IMPLEMENTATION WHEN WE KNOW WHERE AVG_SPREAD IS COMING FROM
export function getAvgSpread(symbol: string): number {
  return Math.random() * 100;
}

import type { TickerDataPayload } from "../context/TickerDataContext";

// File-backed ticker payload helpers (legacy /api/tickers* endpoints).
// The database-backed equity spec lives in ./database.ts.

const API_BASE_URL = "http://localhost:8000/api";

/**
 * Get all available ticker symbols from the backend
 */
export async function getAvailableTickers(): Promise<string[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/tickers`);
    if (!response.ok) {
      throw new Error(`Failed to fetch tickers: ${response.statusText}`);
    }
    const data = await response.json();
    return data.tickers;
  } catch (error) {
    console.error("Error fetching available tickers:", error);
    return [];
  }
}

/**
 * Load payload data for a specific ticker from the backend
 */
export async function loadTickerPayload(symbol: string): Promise<TickerDataPayload> {
  try {
    const response = await fetch(`${API_BASE_URL}/tickers/${symbol}`);
    if (!response.ok) {
      if (response.status === 404) {
        throw new Error(`No data found for symbol: ${symbol}`);
      }
      throw new Error(`Failed to fetch data for ${symbol}: ${response.statusText}`);
    }
    return await response.json();
  } catch (error) {
    console.error(`Error loading ticker data for ${symbol}:`, error);
    throw error;
  }
}

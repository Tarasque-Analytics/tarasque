import type { VolatilityRecord } from "./database";

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000/api";

export interface MacroSectors {
  xlk: VolatilityRecord[];
  xly: VolatilityRecord[];
  xlp: VolatilityRecord[];
  xle: VolatilityRecord[];
  xlf: VolatilityRecord[];
  xlv: VolatilityRecord[];
  xli: VolatilityRecord[];
  xlb: VolatilityRecord[];
  xlre: VolatilityRecord[];
  xlu: VolatilityRecord[];
}

export interface MacroTickers {
  ticker: string,
  vol_history: VolatilityRecord[]
}

export interface MacroDataPayload {
  sectors: MacroSectors;
  tickers: MacroTickers[]
}

export async function loadMacroPayload(uid: string): Promise<MacroDataPayload | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/macro/${uid}`);
    if (!response.ok) return null;
    return (await response.json()) as MacroDataPayload;
  } catch (error) {
    if (import.meta.env.DEV) {
      console.error("Error loading Macros:", error);
    } else {
      console.error("Error loading Macros");
    }
    return null;
  }
}
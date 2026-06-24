import { createContext, useContext } from "react";
import type { ReactNode } from "react";
import type { EquitiesPayload } from "../utils/database";

// Holds the database-backed equity payload (GET /api/equity/:symbol) for the /equity/:symbol
// page. Value is null when the API is unavailable so the page can still render.
export const EquityDataContext = createContext<EquitiesPayload | null>(null);

interface EquityDataProviderProps {
  data: EquitiesPayload | null;
  children: ReactNode;
}

export function EquityDataProvider({ data, children }: EquityDataProviderProps) {
  return <EquityDataContext.Provider value={data}>{children}</EquityDataContext.Provider>;
}

export function useEquityData(): EquitiesPayload | null {
  return useContext(EquityDataContext);
}

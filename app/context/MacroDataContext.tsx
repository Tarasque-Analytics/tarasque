import { createContext, useContext } from "react";
import type { ReactNode } from "react";
import type { MacroDataPayload } from "../utils/macro";

// Holds the database-backed macro sectors payload (GET /api/macro/sectors) for the /macro
// page. Value is null when the API is unavailable so the page can still render.
export const MacroDataContext = createContext<MacroDataPayload | null>(null);

interface MacroDataProviderProps {
  data: MacroDataPayload | null;
  children: ReactNode;
}

export function MacroDataProvider({ data, children }: MacroDataProviderProps) {
  return <MacroDataContext.Provider value={data}>{children}</MacroDataContext.Provider>;
}

export function useMacroData(): MacroDataPayload | null {
  return useContext(MacroDataContext);
}
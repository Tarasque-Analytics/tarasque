import { createContext, useContext } from "react";
import type { ReactNode } from "react";
import type { ModelDataPayload } from "../utils/model";

const API_BASE_URL = "http://localhost:8000/api";

// Holds the database-backed equity payload (GET /api/equity/:symbol) for the /equity/:symbol
// page. Value is null when the API is unavailable so the page can still render.
export const ModelDataContext = createContext<ModelDataPayload | null>(null);

interface ModelDataProviderProps {
  data: ModelDataPayload | null;
  children: ReactNode;
}

export function ModelDataProvider({ data, children }: ModelDataProviderProps) {
  return (
    <ModelDataContext.Provider value={data}>
      {children}
    </ModelDataContext.Provider>
  );
}

export function useModelData(): ModelDataPayload | null {
  return useContext(ModelDataContext);
}
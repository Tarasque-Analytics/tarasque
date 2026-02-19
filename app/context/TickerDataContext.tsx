import { useContext, createContext, useMemo } from 'react';
import type { ReactNode } from 'react';

// Raw JSON payload shape
export type TickerDataPayload = any;

// Parsed and structured data for component consumption
export interface ParsedTickerData {
  meta: any;              // For attributes component
  hedging: any;           // Stored for later use
  explainability: any;    // For predictors component
  monteCarloData: any;    // For monte_carlo component
  opportunities: any[];   // For options component
}

export const TickerDataContext = createContext<ParsedTickerData | null>(null);

interface TickerDataProviderProps {
  data: TickerDataPayload;
  children: ReactNode;
}

export function TickerDataProvider({ data, children }: TickerDataProviderProps) {
  const parsedData = useMemo<ParsedTickerData>(() => ({
    meta: data.meta,
    hedging: data.hedging,
    explainability: data.explainability,
    monteCarloData: data.charts.monte_carlo,
    opportunities: data.opportunities,
  }), [data]);

  return (
    <TickerDataContext.Provider value={parsedData}>
      {children}
    </TickerDataContext.Provider>
  );
}

export function useTickerData(): ParsedTickerData {
  const context = useContext(TickerDataContext);
  if (!context) {
    throw new Error('useTickerData must be used within TickerDataProvider');
  }
  return context;
}

import { useContext, createContext } from 'react';
import type { ReactNode } from 'react';

// Raw JSON payload shape - adjust type as needed once you examine MS_Payload.json
export type TickerDataPayload = any;

export const TickerDataContext = createContext<TickerDataPayload | null>(null);

interface TickerDataProviderProps {
  data: TickerDataPayload;
  children: ReactNode;
}

export function TickerDataProvider({ data, children }: TickerDataProviderProps) {
  return (
    <TickerDataContext.Provider value={data}>
      {children}
    </TickerDataContext.Provider>
  );
}

export function useTickerData(): TickerDataPayload {
  const context = useContext(TickerDataContext);
  if (!context) {
    throw new Error('useTickerData must be used within TickerDataProvider');
  }
  return context;
}

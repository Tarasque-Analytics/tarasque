import { useContext, createContext, useMemo } from 'react';
import type { ReactNode } from 'react';

export interface Holding {
    id: number;
    ticker: string;
    quantity: number;
    price_bought: number;
    created_at: string;
    updated_at: string;
}

export interface PortfolioData {
    holdings: Holding[];
}

export const PortfolioDataContext = createContext<PortfolioData | null>(null);

interface PortfolioDataProviderProps {
    data: PortfolioData;
    children: ReactNode;
}

export function PortfolioDataProvider({ data, children }: PortfolioDataProviderProps) {
    const parsedData = useMemo<PortfolioData>(() => ({
        holdings: data.holdings.map(holding => ({
            ...holding,
        })),
    }), [data]);

    return (
        <PortfolioDataContext.Provider value={parsedData}>
            {children}
        </PortfolioDataContext.Provider>
    );
}

export function usePortfolioData(): PortfolioData {
    const context = useContext(PortfolioDataContext);
    if (!context) {
        throw new Error('usePortfolioData must be used within PortfolioDataProvider');
    }
    return context;
}

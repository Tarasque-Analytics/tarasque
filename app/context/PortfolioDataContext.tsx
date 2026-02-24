import { useContext, createContext, useMemo } from 'react';
import type { ReactNode } from 'react';

export interface Holding {
    id: number;
    ticker: string;
    quantity: number;
    price_bought: number;
    created_at: string;
    updated_at: string;
    current_price: number;
    gain_loss: number; // This will be calculated and added in the provider for easier sorting and display in components
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
            current_price: holding.current_price || holding.price_bought * (1 + (Math.random() - 0.5) * 0.2), // TODO Replace with real current price when available
            gain_loss: holding.current_price 
                ? (holding.current_price - holding.price_bought) * holding.quantity
                : (Math.random() - 0.5) * 20 // TODO: Replace with real gain/loss calculation when current_price is available
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


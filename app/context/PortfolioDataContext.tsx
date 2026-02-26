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

// TODO: Implement logic to get real current prices for holdings
export function getCurrentPrices() : Record<string, number> {
    const portfolioData = usePortfolioData();
    const prices: Record<string, number> = useMemo(() => { // cache the prices
        const result: Record<string, number> = {};
        for (const holding of portfolioData.holdings) {
            result[holding.ticker] = (Math.random() - 0.5) * 20 + holding.price_bought; // Placeholder logic, replace with real price fetching
        }
        return result;
    }, [portfolioData.holdings]);
    return prices;
}

export function gainLossPercent(): Record<string, number> {
    const currentPrices = getCurrentPrices();
    const portfolioData = usePortfolioData();
    const gainLoss: Record<string, number> = useMemo(() => {
        const gainLoss: Record<string, number> = {};
        for (const holding of portfolioData.holdings) {
            const currentPrice = currentPrices[holding.ticker];
            gainLoss[holding.ticker] = (currentPrice - holding.price_bought) / holding.price_bought * 100;
        }
        return gainLoss;
    }, [currentPrices, portfolioData.holdings]);
    return gainLoss
}
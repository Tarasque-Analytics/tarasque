// Takes a list containing ticker symbols and returns a mapping of ticker to current price
export function getCurrentPrices(holdings: string[]): Record<string, number> {
    const prices: Record<string, number> = {};
    for (const ticker of holdings) {
        prices[ticker] = (Math.random() - 0.5) * 20 + 100; // Placeholder logic, replace with real price fetching
    }
    return prices;
}

// Takes a list of holdings and current prices, returns a mapping of ticker to gain/loss percentage
export function gainLossPercent(holdings: { ticker: string; price_bought: number }[]): Record<string, number> {
    const currentPrices = getCurrentPrices(holdings.map(h => h.ticker));
    const gainLoss: Record<string, number> = {};
    for (const holding of holdings) {
        const currentPrice = currentPrices[holding.ticker];
        gainLoss[holding.ticker] = (currentPrice - holding.price_bought) / holding.price_bought * 100;
    }
    return gainLoss;
}
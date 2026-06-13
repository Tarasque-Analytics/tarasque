import { useState, useMemo } from "react";
import { usePortfolioData } from "~/context/PortfolioDataContext";
import { getCurrentPrices } from "./portfolio_utils";
import HoldingView from "./holdingView";

export default function PortfolioTickers() {
  const [showAll, setShowAll] = useState(false);
  const portfolioData = usePortfolioData();

  const tickerToPrice = useMemo(
    () => getCurrentPrices(portfolioData.holdings.map((h) => h.ticker)),
    [portfolioData.holdings],
  );

  const totalValue = useMemo( // calculate the total market value of the portfolio
    () =>
      portfolioData.holdings.reduce(
        (sum, holding) => sum + holding.quantity * tickerToPrice[holding.ticker],
        0,
      ),
    [tickerToPrice],
  );

  let weights = useMemo(() => {
    const w: Record<string, number> = {};
    portfolioData.holdings.forEach((holding) => {
      w[holding.ticker] = (holding.quantity * tickerToPrice[holding.ticker]) / totalValue * 100;
    });
    return w;
  }, [portfolioData.holdings, tickerToPrice, totalValue]);

  let weightsList = Object.entries(weights).sort((a, b) => b[1] - a[1]); // sort by weight descending
  const displayedHoldings = showAll ? weightsList : weightsList.slice(0, 5);

  return (
    <div className="flex flex-col justify-center items-center">
      Ticker - Weight - Wedge Percentile
      {displayedHoldings.map((holding) => (
        <HoldingView key={holding[0]} ticker={holding[0]} gain_loss={holding[1]} wedgePercentile={getWedgePercentiles(holding[0])}/>
      ))}
      {weightsList.length > 5 && (
        <button onClick={() => setShowAll(!showAll)} className="view-more-button">
          {showAll ? "View Less" : "View More"}
        </button>
      )}
    </div>
  );
}

export function getWedgePercentiles(ticker: string): number {
  return Math.floor(Math.random() * 100) + 1; // Placeholder logic, replace with real percentile calculation once the model and database are set up
}
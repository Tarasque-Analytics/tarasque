import { useState, useMemo } from "react";
import { usePortfolioData } from "~/context/PortfolioDataContext";
import { gainLossPercent } from "./portfolio_utils";
import HoldingView from "./holdingView";

export default function PortfolioTickers() {
    const [showAll, setShowAll] = useState(false);
    const portfolioData = usePortfolioData();
    const gainLoss = useMemo(() => Object.entries(gainLossPercent(portfolioData.holdings)), [portfolioData.holdings]);      


    
    // // Sort by gain_loss descending, ensuring gain_loss is always a number
    const sortedHoldings = useMemo(() => {
        return gainLoss.sort((a, b) => { return b[1] - a[1]})
    }, [gainLoss]);

    const displayedHoldings = showAll ? sortedHoldings : sortedHoldings.slice(0, 5);

    return (
        <div className="portfolio-tickers">
            {displayedHoldings.map((holding) => (
                <HoldingView key={holding[0]} ticker={holding[0]} gain_loss={holding[1]} />
            ))}
            {sortedHoldings.length > 3 && (
                <button onClick={() => setShowAll(!showAll)} className="view-more-button">
                    {showAll ? "View Less" : "View More"}
                </button>
            )}
        </div>
    )
}
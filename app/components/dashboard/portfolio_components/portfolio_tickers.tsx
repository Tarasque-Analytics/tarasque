import { useState, useMemo } from "react";
import { usePortfolioData } from "~/context/PortfolioDataContext";
import HoldingView from "./holdingView";

export default function PortfolioTickers() {
    const [showAll, setShowAll] = useState(false);

    const { holdings } = usePortfolioData();
    
    // Sort by gain_loss descending, ensuring gain_loss is always a number
    const sortedHoldings = useMemo(() => 
        [...holdings]
            .filter(holding => holding.gain_loss !== undefined) // Nothing should be undefined, but just in case
            .sort((a, b) => (b.gain_loss || 0) - (a.gain_loss || 0)),
        [holdings]
    );

    const displayedHoldings = showAll ? sortedHoldings : sortedHoldings.slice(0, 5);

    return (
        <div>
            {displayedHoldings.map((holding) => (
                <HoldingView key={holding.id} {...holding} />
            ))}
            {sortedHoldings.length > 3 && (
                <button onClick={() => setShowAll(!showAll)} className="view-more-button">
                    {showAll ? "View Less" : "View More"}
                </button>
            )}
        </div>
    )
}
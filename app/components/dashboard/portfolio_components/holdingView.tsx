import { useEffect, useState } from "react";
import { Link } from "react-router";

export interface HoldingProps {
    ticker: string;
    gain_loss: number;
}

// holding = {ticker: string, gain_loss: number} 
export default function HoldingView(holding: HoldingProps) {
    const [symbol, setSymbol] = useState(holding.ticker);

    const [percentChange, setPercentChange] = useState(holding?.gain_loss || 0);

    return (
        <div className="ticker-gain-loss">
            <div className="symbol">{symbol} -</div>
            <div className={`percent-change ${percentChange >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                {percentChange.toFixed(2)}%
            </div>
        </div>
    )
}
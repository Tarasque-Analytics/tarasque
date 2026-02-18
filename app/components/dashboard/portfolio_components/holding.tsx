import { useEffect, useState } from "react";
import { Link } from "react-router";

interface HoldingProps {
  id: number;
  ticker: string;
  quantity: number;
  price_bought: number;
}


// holding = {ticker: string, price_bought: number} 
export default function Holding(holding: HoldingProps) {
    const [symbol, setSymbol] = useState(holding.ticker);

    // TODO: Fetch current price from API
    const current_price = holding.price_bought * (1 + (Math.random() - 0.5) * 0.1);

    const [percentChange, setPercentChange] = useState((current_price - holding.price_bought) / holding.price_bought * 100);

    return (
        <div className="flex gap-2 w-full">
            <div className="symbol">{symbol} -</div>
            <div className={`percent-change ${percentChange >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                {percentChange.toFixed(2)}%
            </div>
        </div>
    )
}
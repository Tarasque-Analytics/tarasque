export interface HoldingProps {
  ticker: string;
  gain_loss: number;
  wedgePercentile: number;
}

// holding = {ticker: string, gain_loss: number}
export default function HoldingView(holding: HoldingProps) {
  const symbol = holding.ticker;
  const percentChange = holding.gain_loss;
  const wedge = holding.wedgePercentile;
  return (
    <div className="ticker-gain-loss">
      <div>{symbol}: </div>
      <div className={`percent-change ${percentChange >= 0 ? "text-green-600" : "text-red-600"}`}>
        {percentChange.toFixed(2)}%
      </div>
      <div> - {wedge}{getOrdinalSuffix(wedge)}</div>
    </div>
  );
}

export function getOrdinalSuffix(num: number): string {
  const lastDigit = num % 10;
  const secLastDigit = num % 100;
  if (secLastDigit >= 11 && secLastDigit <= 13) {
    return "th";
  } else if (lastDigit === 1) {
    return "st";
  } else if (lastDigit === 2) {
    return "nd";
  } else if (lastDigit === 3) {
    return "rd";
  } else {
    return "th";
  }
}

import { Link, useParams } from "react-router";
import { useState, useEffect } from "react";
import HedgingRecommendations from "../components/ticker/hedging_recommendations";
import Options from "../components/ticker/options";
import Predictors from "../components/ticker/predictors";

export default function TickerView() {
  const { symbol } = useParams<{ symbol: string }>();
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // TODO: Fetch ticker data from API endpoint
    // For now, just simulate loading
    const timer = setTimeout(() => setIsLoading(false), 200);
    return () => clearTimeout(timer);
  });

  return (
    <div>
      <h1>Ticker</h1>
      <Link to="/">Go home</Link>
      {/* Page Grid Styles */}
      <div className="ticker">
        {/* Left Column */}
        <div className="ticker-left">
          {isLoading ? (
            <div className="loading-placeholder" />
          ) : (
            <HedgingRecommendations />
          )}
        </div>

        {/* Center Column */}
        <div className="ticker-center">
          {isLoading ? (
            <div className="loading-placeholder" />
          ) : (
            <Predictors />
          )}
        </div>

        {/* Right Column */}
        <div className="ticker-right">
          {isLoading ? (
            <div className="loading-placeholder" />
          ) : (
            <Options />
          )}
        </div>
      </div>
    </div>
  );
}

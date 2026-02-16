import { Link, useParams, useLoaderData } from "react-router";
import { useState, useEffect } from "react";
import HedgingRecommendations from "../components/ticker/hedging_recommendations";
import Options from "../components/ticker/options";
import Predictors from "../components/ticker/predictors";
import type { TickerDataPayload } from "../context/TickerDataContext";
import { TickerDataProvider } from "../context/TickerDataContext";

export default function TickerView() {
  const { symbol } = useParams<{ symbol: string }>();
  const payloadData = useLoaderData() as TickerDataPayload;
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Data is preloaded from route loader
    setIsLoading(false);
  }, []);

  return (
    <TickerDataProvider data={payloadData}>
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
            {isLoading ? <div className="loading-placeholder" /> : <Options />}
          </div>

          {/* Right Column */}
          <div className="ticker-right">
            {isLoading ? <div className="loading-placeholder" /> : <Predictors />}
          </div>
        </div>
      </div>
    </TickerDataProvider>
  );
}

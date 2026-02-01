import { useParams } from "react-router";
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
    const timer = setTimeout(() => setIsLoading(false), 500);
    return () => clearTimeout(timer);
  }, [symbol]);

  return (
    <div className="flex-1 p-6">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900">{symbol}</h1>
      </div>

      {/* 3-Column Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3">
        {/* Left Column */}
        <div className="flex flex-col">
          {isLoading ? (
            <div className="bg-gray-200 h-64 rounded animate-pulse" />
          ) : (
            <HedgingRecommendations />
          )}
        </div>

        {/* Center Column */}
        <div className="flex flex-col">
          {isLoading ? (
            <div className="bg-gray-200 h-96 rounded animate-pulse" />
          ) : (
            <Predictors />
          )}
        </div>

        {/* Right Column */}
        <div className="flex flex-col">
          {isLoading ? (
            <div className="bg-gray-200 h-64 rounded animate-pulse" />
          ) : (
            <Options />
          )}
        </div>
      </div>
    </div>
  );
}

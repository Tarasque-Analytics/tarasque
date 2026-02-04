import { useEffect, useState } from "react";
import { Link } from "react-router";
import PortfolioOverview from "../components/dashboard/portfolio_overview";
import HedgingInfo from "../components/dashboard/hedging_info";
import SectorView from "../components/dashboard/sector_view";
import DetailedAnalysis from "../components/dashboard/detailed_analysis";
export default function Dashboard() {
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    // TODO: Fetch user's portfolio from db
    const timer = setTimeout(() => setIsLoading(false), 500);
    return () => clearTimeout(timer);
  });

  return (
    <div>
      <h1>Dashboard</h1>
      <Link to="/">Go home</Link>
      <div className="flex-1 p-6">
        {/* 6-Column Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-6 grid-rows-3">
          {/* Left Column */}
          <div className="flex flex-col col-start-1 col-span-1 row-span-3">
            {isLoading ? (
              <div className="bg-gray-200 h-64 rounded animate-pulse" />
            ) : (
              <PortfolioOverview />
            )}
          </div>

          {/* Center Column */}
          <div className="flex flex-col col-start-2 col-span-3 row-span-3">
            {isLoading ? (
              <div className="bg-gray-200 h-96 rounded animate-pulse" />
            ) : (
              <div>
                <DetailedAnalysis />
                <HedgingInfo />
              </div>
            )}
          </div>

          {/* Right Column */}
          <div className="flex flex-col col-start-5 col-span-2 row-span-3">
            {isLoading ? (
              <div className="bg-gray-200 h-64 rounded animate-pulse" />
            ) : (
              <SectorView />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { Link } from "react-router";
import PortfolioOverview from "../components/dashboard/portfolio_overview";
import HedgingInfo from "../components/dashboard/hedging_info";
import SectorView from "../components/dashboard/sector_view";
import DetailedAnalysis from "../components/dashboard/detailed_analysis";
export default function Dashboard() {
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // TODO: Fetch user's portfolio from db
    const timer = setTimeout(() => setIsLoading(false), 200);
    return () => clearTimeout(timer);
  });

  return (
    <div>
      <h1>Dashboard</h1>
      <Link to="/">Go home</Link>
      {/* Page Grid Styles */}
      <div className="grid grid-cols-6">
        {/* Left Column */}
        <div className="col-start-1 col-span-1 p-2">
          {isLoading ? (
            <div className="loading-placeholder" />
          ) : (
            <PortfolioOverview />
          )}
        </div>

        {/* Center Column */}
        <div className="col-start-2 col-span-3 p-2">
          <div className="pb-2">
            {isLoading ? (
              <div className="loading-placeholder" />
            ) : (
              <DetailedAnalysis />
            )}
          </div>
          <div className="pt-2">
            {isLoading ? (
              <div className="loading-placeholder" />
            ) : (
              <HedgingInfo />
            )}
          </div>
        </div>

        {/* Right Column */}
        <div className="col-start-5 col-span-2 row-span-3 p-2">
          {isLoading ? <div className="loading-placeholder" /> : <SectorView />}
        </div>
      </div>
    </div>
  );
}

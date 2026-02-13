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
      <div className="dashboard">
        {/* Left Column */}
        <div className="dashboard-left">
          {isLoading ? (
            <div className="loading-placeholder" />
          ) : (
            <PortfolioOverview />
          )}
        </div>

        {/* Center Column */}
        <div className="dashboard-center">
          <div className="dashboard-center-top">
            {isLoading ? (
              <div className="loading-placeholder" />
            ) : (
              <DetailedAnalysis />
            )}
          </div>
          <div className="dashboard-center-bottom">
            {isLoading ? (
              <div className="loading-placeholder" />
            ) : (
              <HedgingInfo />
            )}
          </div>
        </div>

        {/* Right Column */}
        <div className="dashboard-right">
          {isLoading ? <div className="loading-placeholder" /> : <SectorView />}
        </div>
      </div>
    </div>
  );
}

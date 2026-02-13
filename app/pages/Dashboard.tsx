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
        <div className="dashboard">
          {/* Left Column */}
          <div className="dashboard-left">
            <PortfolioOverview />
          </div>

          {/* Center Column */}
          <div className="dashboard-center">
            <div className="dashboard-center-top">
              <DetailedAnalysis />
            </div>
            <div className="dashboard-center-bottom">
              <HedgingInfo />
            </div>
          </div>

          {/* Right Column */}
          <div className="dashboard-right">
            <SectorView />
          </div>
        </div>
      </div>
    </div>
  );
}

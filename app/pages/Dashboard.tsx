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
      <div className="flex justify-center">Dashboard</div>
      <Link to="/" className="flex justify-center">
        Go to Navigation
      </Link>
      {/* Component Grid */}
      {isLoading ? (
        <div className="loading-placeholder" />
      ) : (
        <div className="grid grid-cols-6">
          {/* Left Column */}
          <div className="col-start-1 col-span-1 p-2">
            <div className="dashboard-section">
              <PortfolioOverview />
            </div>
          </div>

          {/* Center Column */}
          <div className="col-start-2 col-span-3 p-2">
            <div className="pb-2">
              <DetailedAnalysis />
            </div>
            <div className="pt-2">
              <HedgingInfo />
            </div>
          </div>

          {/* Right Column */}
          <div className="col-start-5 col-span-2 row-span-3 p-2">
            <SectorView />
          </div>
        </div>
      )}
    </div>
  );
}

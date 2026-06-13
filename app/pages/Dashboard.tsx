import { useEffect, useState } from "react";
import DashboardLeft from "../components/dashboard/dashboard_left";
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

      {/* Component Grid */}
      {isLoading ? (
        <div className="loading-placeholder" />
      ) : (
        <div className="grid grid-cols-4">
          {/* Left Column */}
          <div className="col-start-1 col-span-1 p-2">
            <div className="dashboard-section">
              <DashboardLeft />
            </div>
          </div>

          {/* Center Column */}
          <div className="col-start-2 col-span-2 p-2">
            <div className="dashboard-section">
              <DetailedAnalysis />
            </div>
          </div>

          {/* Right Column */}
          <div className="col-start-4 col-span-1 row-span-3 p-2">
            <div className="dashboard-section">
              <HedgingInfo />
            </div>
            <div className="dashboard-section">
              <SectorView />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

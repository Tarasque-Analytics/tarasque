import DashboardLeft from "../components/dashboard/dashboard_left";
import HedgingInfo from "../components/dashboard/hedging_info";
import SectorView from "../components/dashboard/sector_view";
import DetailedAnalysis from "../components/dashboard/detailed_analysis";

export default function Dashboard() {
  return (
    <div>
      {/* Component Grid */}
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
    </div>
  );
}

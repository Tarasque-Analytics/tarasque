// 3d model, still have to iron this out
import { PortfolioDataProvider } from "~/context/PortfolioDataContext";
import Placeholder from "../ui/placeholder";
import PortfolioGraph from "./portfolio_components/portfolio_graph";
import portfoliodata from "./portfolio_components/test_portfolio.json"; // PLACEHOLDER DATA

export default function DetailedAnalysis() {
  return (
    <div className="bg-white rounded-lg shadow p-6">
      <PortfolioDataProvider data={portfoliodata}>
        <PortfolioGraph />
      </PortfolioDataProvider>
    </div>
  );
}

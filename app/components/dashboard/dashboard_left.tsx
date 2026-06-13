// farily basic stuff, the top 5 holdings, with a show more drop down, a pie chart of securities, and a standard panel graph showing the time and capital growth
import PortfolioTickers from "./portfolio_components/portfolio_tickers";
import { PortfolioDataProvider } from "../../context/PortfolioDataContext";
import PortfolioPieChart from "./portfolio_components/portfolio_pie_chart";
import WedgeDistribution from "./wedge_distribution";

import portfoliodata from "./portfolio_components/test_portfolio.json"; // PLACEHOLDER DATA

export default function DashboardLeft() {
  return (
    <div className="flex flex-col gap-4">
      {/* <h2 className="dashboard-section-title">Portfolio Overview</h2> */}
      <PortfolioDataProvider data={portfoliodata}>
        <PortfolioPieChart />
        <PortfolioTickers />
        <WedgeDistribution />
      </PortfolioDataProvider>
    </div>
  );
}

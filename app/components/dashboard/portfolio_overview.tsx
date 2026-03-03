// farily basic stuff, the top 5 holdings, with a show more drop down, a pie chart of securities, and a standard panel graph showing the time and capital growth
import Placeholder from "../ui/placeholder";
import PortfolioTickers from "./portfolio_components/portfolio_tickers";
import portfoliodata from "./portfolio_components/test_portfolio.json";
import { PortfolioDataProvider } from "../../context/PortfolioDataContext";
import PortfolioPieChart from "./portfolio_components/portfolio_pie_chart";
import PortfolioGraph from "./portfolio_components/portfolio_graph";
export default function PortfolioOverview() {
  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Portfolio Overview</h2>
      <PortfolioDataProvider data={portfoliodata}>
        <PortfolioTickers />
        <PortfolioPieChart />
        <PortfolioGraph />
      </PortfolioDataProvider>
    </div>
  );
}

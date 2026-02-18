// farily basic stuff, the top 5 holdings, with a show more drop down, a pie chart of securities, and a standard panel graph showing the time and capital growth
import Placeholder from '../ui/placeholder';
import PortfolioTickers from './portfolio_components/portfolio_tickers';
export default function PortfolioOverview() {
  return (
    <div className="dashboard-section">
      <h2 className="dashboard-section-title">Portfolio Overview</h2>
      <PortfolioTickers />
    </div>
  );
}
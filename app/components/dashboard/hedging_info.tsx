// from the seperate hedging model that runs a complete diagnostic on the portfolio including delta, gamma, and factor exposures.
import Placeholder from '../ui/placeholder';
import PortfolioGraph from './portfolio_components/portfolio_graph';
import { PortfolioDataProvider } from '../../context/PortfolioDataContext';
import portfoliodata from "./portfolio_components/test_portfolio.json";
export default function HedgingInfo() {

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Hedging Information</h2>
      <Placeholder />
    </div>
  );
}
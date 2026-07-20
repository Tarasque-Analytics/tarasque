import { useLoaderData, useParams } from "react-router";
import Search from "~/components/ui/search";
import PriceHistoryChart from "../components/equity/price_history_chart";
import EquityMetaData from "~/components/equity/metadata";
import ForwardVolForecast from "../components/equity/forward_vol_forecast";
import OptionsChainTable from "../components/equity/options_chain_table";
import ContractSkewChart from "../components/equity/contract_skew_chart";
import DistributionChart from "../components/equity/distribution_chart";
import EquityUnavailable from "../components/equity/equity_unavailable";
import { EquityDataProvider } from "../context/EquityDataContext";
import type { TickerLoaderData } from "../routes/ticker";
import Overview from "../components/equity/overview";
export default function TickerView() {
  const { equity } = useLoaderData() as TickerLoaderData;
  const { symbol } = useParams();

  // The DB-backed payload is the page's only data source now. If the loader couldn't fetch it,
  // show an explicit "unavailable" state rather than an empty shell of components.
  if (!equity) {
    return <EquityUnavailable symbol={symbol} />;
  }

  return (
    <EquityDataProvider data={equity}>
      {/* Redesigned equity page — new components go here */}
      <div className="grid grid-cols-16 gap-4">
        {/* Left col*/}
        <div className="col-span-3 flex flex-col gap-4">
          <Search />
          <EquityMetaData />
        </div>
        {/* Center col*/}
        <div className="col-span-10 flex flex-col gap-6">
          <PriceHistoryChart />
          <ForwardVolForecast />
          <ContractSkewChart />
          <OptionsChainTable />
        </div>
        {/* Right col*/}
        <div className="col-span-3 flex flex-col gap-6">
          <DistributionChart />
        </div>
      </div>
    </EquityDataProvider>
  );
}

import { useLoaderData, useParams } from "react-router";
import { useLoaderData } from "react-router";
import Attributes from "../components/ticker/attributes";
import MonteCarlo from "~/components/ticker/monte_carlo";
import Options from "../components/ticker/options";
import Search from "~/components/ui/search";
import Predictors from "../components/ticker/predictors";
import PriceHistoryChart from "../components/equity/price_history_chart";
import EquityClasses from "~/components/equity/equity_classes";
import ForwardVolForecast from "../components/equity/forward_vol_forecast";
import OptionsChainTable from "../components/equity/options_chain_table";
import ContractSkewChart from "../components/equity/contract_skew_chart";
import EquityUnavailable from "../components/equity/equity_unavailable";
import { EquityDataProvider } from "../context/EquityDataContext";
import type { TickerLoaderData } from "../routes/ticker";

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
      <div className="flex flex-col gap-6">
        {/* DB-backed equity page — new components go here, top-down. */}
        <PriceHistoryChart />
        <ForwardVolForecast />
        <OptionsChainTable />
        <ContractSkewChart />
      </div>
    </EquityDataProvider>
    <TickerDataProvider data={payload}>
      <EquityDataProvider data={equity}>
        {/* Redesigned equity page — new components go here */}
        <div className="grid grid-cols-4 gap-25">
          {/* Left col*/}
          <div className="flex flex-col gap-6">
            <Search />
            <EquityClasses /> 
          </div>
          {/* Center col*/}
          <div className="col-span-2 flex flex-col gap-6">
            <PriceHistoryChart />
            <ForwardVolForecast />
          </div>
          {/* Right col*/}
          <div className="flex flex-col gap-6"></div>
        </div>


          {/* Legacy components below: slated for near-complete rewrite as the redesign
              proceeds. Kept temporarily so the page stays functional; remove as each is
              replaced (and retire the file-payload path once nothing reads it). */}
        <div className="flex flex-col gap-6">

          <div className="grid grid-cols-4 grid-rows-2 gap-4 opacity-60">
            <div>
              <Attributes />
            </div>
            <div className="row-span-2 col-span-2">
              <Options />
            </div>
            <div className="row-span-2">
              <Predictors />
            </div>
            <div>
              <MonteCarlo />
            </div>
          </div>
        </div>
      </EquityDataProvider>
    </TickerDataProvider>
  );
}

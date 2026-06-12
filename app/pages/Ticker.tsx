import { useLoaderData } from "react-router";
import Attributes from "../components/ticker/attributes";
import MonteCarlo from "~/components/ticker/monte_carlo";
import Options from "../components/ticker/options";
import Predictors from "../components/ticker/predictors";
import PriceHistoryChart from "../components/equity/price_history_chart";
import ForwardVolForecast from "../components/equity/forward_vol_forecast";
import ContractSkewChart from "../components/equity/contract_skew_chart";
import { TickerDataProvider } from "../context/TickerDataContext";
import { EquityDataProvider } from "../context/EquityDataContext";
import type { TickerLoaderData } from "../routes/ticker";

export default function TickerView() {
  const { payload, equity } = useLoaderData() as TickerLoaderData;

  return (
    <TickerDataProvider data={payload}>
      <EquityDataProvider data={equity}>
        <div className="flex flex-col gap-6">
          {/* Redesigned equity page — new components go here, top-down. */}
          <PriceHistoryChart />
          <ForwardVolForecast />
          <ContractSkewChart />

          {/* Legacy components below: slated for near-complete rewrite as the redesign
              proceeds. Kept temporarily so the page stays functional; remove as each is
              replaced (and retire the file-payload path once nothing reads it). */}
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

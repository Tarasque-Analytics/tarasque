import { useParams, useLoaderData } from "react-router";
import Attributes from "../components/ticker/attributes";
import MonteCarlo from "~/components/ticker/monte_carlo";
import Options from "../components/ticker/options";
import Predictors from "../components/ticker/predictors";
import { TickerDataProvider } from "../context/TickerDataContext";
import { EquityDataProvider } from "../context/EquityDataContext";
import type { TickerLoaderData } from "../routes/ticker";

export default function TickerView() {
  const { symbol } = useParams<{ symbol: string }>();
  const { payload, equity } = useLoaderData() as TickerLoaderData;

  return (
    <TickerDataProvider data={payload}>
      <EquityDataProvider data={equity}>
        <div>
          <div className="flex justify-center">Data and Analytics for {symbol}</div>
          {/* Component Grid */}
          <div className="grid grid-cols-4 grid-rows-2 gap-4">
            <div className="">
              <Attributes />
            </div>
            <div className="row-span-2 col-span-2">
              <Options />
            </div>
            <div className="row-span-2">
              <Predictors />
            </div>
            <div className="">
              <MonteCarlo />
            </div>
          </div>
        </div>
      </EquityDataProvider>
    </TickerDataProvider>
  );
}

import { useParams, useLoaderData } from "react-router";
import { useState, useEffect } from "react";
import Attributes from "../components/ticker/attributes";
import MonteCarlo from "~/components/ticker/monte_carlo";
import Options from "../components/ticker/options";
import Predictors from "../components/ticker/predictors";
import type { TickerDataPayload } from "../context/TickerDataContext";
import { TickerDataProvider } from "../context/TickerDataContext";

export default function TickerView() {
  const { symbol } = useParams<{ symbol: string }>();
  const payloadData = useLoaderData() as TickerDataPayload;
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Data is preloaded from route loader
    setIsLoading(false);
  }, []);

  return (
    <TickerDataProvider data={payloadData}>
      <div>
        <div className="flex justify-center">Data and Analytics for {symbol}</div>
        {/* Component Grid */}
        {isLoading ? (
          <div className="loading-placeholder" />
        ) : (
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
        )}
      </div>
    </TickerDataProvider>
  );
}

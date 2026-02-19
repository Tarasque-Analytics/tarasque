import { Link, useParams, useLoaderData } from "react-router";
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
        <h1>Ticker</h1>
        <Link to="/">Go home</Link>
        {/* Component Grid */}
        {isLoading ? (
          <div className="loading-placeholder" />
        ) : (
          <div className="ticker">
            <div className="attributes-box">
              <Attributes />
            </div>
            <div className="monte-carlo-box">
              <MonteCarlo />
            </div>
            <div className="options-box">
              <Options />
            </div>
            <div className="predictors-box">
              <Predictors />
            </div>
          </div>
        )}
      </div>
    </TickerDataProvider>
  );
}

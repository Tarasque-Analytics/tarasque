import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import PriceHistoryChart from "./price_history_chart";
import { makeEquityPayload, renderWithEquity } from "~/test/equity-test-utils";

describe("PriceHistoryChart", () => {
  it("shows the unavailable placeholder when no equity data is provided", () => {
    render(<PriceHistoryChart />);
    expect(screen.getByText(/price data is currently unavailable/i)).toBeInTheDocument();
  });

  it("shows the no-data placeholder when price history is empty", () => {
    renderWithEquity(<PriceHistoryChart />, makeEquityPayload({ price_history: [] }));
    expect(screen.getByText(/no price history available for AAPL/i)).toBeInTheDocument();
  });
});

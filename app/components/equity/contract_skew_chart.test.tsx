import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ContractSkewChart from "./contract_skew_chart";
import { makeEquityPayload, renderWithEquity } from "~/test/equity-test-utils";

describe("ContractSkewChart", () => {
  it("shows the unavailable placeholder when no equity data is provided", () => {
    render(<ContractSkewChart />);
    expect(screen.getByText(/options data is currently unavailable/i)).toBeInTheDocument();
  });

  it("shows the no-data placeholder when the options chain is empty", () => {
    renderWithEquity(
      <ContractSkewChart />,
      makeEquityPayload({ options_chain: [], price_history: [] }),
    );
    expect(screen.getByText(/no options chain available for AAPL/i)).toBeInTheDocument();
  });
});

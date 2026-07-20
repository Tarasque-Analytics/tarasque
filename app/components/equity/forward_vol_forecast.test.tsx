import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ForwardVolForecast from "./forward_vol_forecast";
import { makeEquityPayload, renderWithEquity } from "~/test/equity-test-utils";

describe("ForwardVolForecast", () => {
  it("shows the unavailable placeholder when no equity data is provided", () => {
    render(<ForwardVolForecast />);
    expect(screen.getByText(/forward vol data is currently unavailable/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /forward vol forecast/i })).toBeInTheDocument();
  });

  it("shows the no-data placeholder when volatility history is empty", () => {
    renderWithEquity(<ForwardVolForecast />, makeEquityPayload({ volatility_history: [] }));
    expect(
      screen.getByText(/no volatility term structure available for AAPL/i),
    ).toBeInTheDocument();
  });
});

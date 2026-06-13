import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import EquityUnavailable from "./equity_unavailable";

describe("EquityUnavailable", () => {
  it("renders the unavailable heading inside an alert region", () => {
    render(<EquityUnavailable />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /equity data unavailable/i }),
    ).toBeInTheDocument();
  });

  it("shows the uppercased symbol in the message when one is provided", () => {
    render(<EquityUnavailable symbol="aapl" />);
    expect(screen.getByText(/load data for AAPL/i)).toBeInTheDocument();
  });

  it("falls back to a generic message when no symbol is given", () => {
    render(<EquityUnavailable />);
    expect(screen.getByText(/load equity data right now/i)).toBeInTheDocument();
  });
});

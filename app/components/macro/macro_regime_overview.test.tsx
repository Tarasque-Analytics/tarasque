import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import MacroRegimeOverview from "./macro_regime_overview";

describe("MacroRegimeOverview", () => {
  it("renders the banner heading, regime badge, and wedge stat chips", () => {
    render(<MacroRegimeOverview />);
    expect(
      screen.getByRole("heading", { name: /macro · cross-section regime/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/mid-cycle · widening dispersion/i)).toBeInTheDocument();
    // Right-aligned VRP wedge stat chips (size + percentile).
    expect(screen.getByText("WEDGE")).toBeInTheDocument();
    expect(screen.getByText("WEDGE %ILE")).toBeInTheDocument();
    expect(screen.getByText("+4.6 pp")).toBeInTheDocument();
    expect(screen.getByText("68th")).toBeInTheDocument();
  });
});

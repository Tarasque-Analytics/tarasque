import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import Macro from "./Macro";

// The page is pure composition (no loader data, no router hooks), so it renders standalone. This
// asserts the section stack mounts — one distinctive marker per issue-driven section.
describe("Macro page", () => {
  it("renders the issue-driven section stack", () => {
    render(<Macro />);
    // NEXT FOMC (#134)
    expect(screen.getByRole("heading", { name: "NEXT FOMC" })).toBeInTheDocument();
    // Macro regime overview banner (#135)
    expect(screen.getByText("S&P large-cap corpus · NN names")).toBeInTheDocument();
    // Regime scatter centerpiece (#132/#133)
    expect(screen.getByText(/regime scatter pending data/i)).toBeInTheDocument();
  });

  it("renders the supporting placeholder cards", () => {
    render(<Macro />);
    expect(screen.getByRole("heading", { name: "Watchlist" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sector heatmap" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Macro AI overview" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Wedge dispersion" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Fed / macro events" })).toBeInTheDocument();
  });
});

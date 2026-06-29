import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import RegimeScatter from "./regime_scatter";

describe("RegimeScatter", () => {
  it("renders the default (Cross-section regime) lens with axes, legend, and placeholder", () => {
    render(<RegimeScatter />);
    expect(screen.getByRole("heading", { name: "Cross-section regime" })).toBeInTheDocument();
    expect(screen.getByText(/regime scatter pending data/i)).toBeInTheDocument();
    // Lens A axis titles + legend heading; Lens B quadrant corners are absent until switched.
    expect(screen.getByText("Market-reactivity β (CAPM)")).toBeInTheDocument();
    expect(screen.getByText("Reading the chart")).toBeInTheDocument();
    expect(screen.queryByText("Cheap & Feared")).not.toBeInTheDocument();
  });

  it("exposes Lens / View / Horizon toggles with the expected defaults active", () => {
    render(<RegimeScatter />);
    expect(screen.getByRole("button", { name: "Regime" })).toHaveAttribute("data-active", "true");
    expect(screen.getByRole("button", { name: "Vol vs Value" })).toHaveAttribute(
      "data-active",
      "false",
    );
    expect(screen.getByRole("button", { name: "Sector" })).toHaveAttribute("data-active", "true");
    expect(screen.getByRole("button", { name: "Tickers" })).toHaveAttribute("data-active", "false");
    expect(screen.getByRole("button", { name: "63d" })).toHaveAttribute("data-active", "true");
    expect(screen.getByRole("button", { name: "21d" })).toHaveAttribute("data-active", "false");
  });

  it("switches to the Vol vs Value lens, swapping axis title, legend, and quadrant corners", () => {
    render(<RegimeScatter />);
    fireEvent.click(screen.getByRole("button", { name: "Vol vs Value" }));

    expect(screen.getByRole("heading", { name: "Vol vs Value" })).toBeInTheDocument();
    expect(screen.getByText("Vol percentile (0–100)")).toBeInTheDocument();
    expect(screen.getByText("Quadrants")).toBeInTheDocument();
    // "Cheap & Feared" now appears as both a quadrant corner and a legend entry.
    expect(screen.getAllByText("Cheap & Feared").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("button", { name: "Vol vs Value" })).toHaveAttribute(
      "data-active",
      "true",
    );
  });
});

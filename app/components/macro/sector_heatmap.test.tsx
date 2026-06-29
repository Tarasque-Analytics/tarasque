import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import SectorHeatmap from "./sector_heatmap";

describe("SectorHeatmap", () => {
  it("renders its header and the placeholder", () => {
    render(<SectorHeatmap />);
    expect(screen.getByRole("heading", { name: "Sector heatmap" })).toBeInTheDocument();
    expect(screen.getByText(/sector heatmap coming soon/i)).toBeInTheDocument();
  });
});

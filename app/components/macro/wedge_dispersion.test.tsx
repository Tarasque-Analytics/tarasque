import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import WedgeDispersion from "./wedge_dispersion";

describe("WedgeDispersion", () => {
  it("renders its header and the placeholder", () => {
    render(<WedgeDispersion />);
    expect(screen.getByRole("heading", { name: "Wedge dispersion" })).toBeInTheDocument();
    expect(screen.getByText(/dispersion histogram coming soon/i)).toBeInTheDocument();
  });
});

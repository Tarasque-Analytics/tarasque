import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import Watchlist from "./watchlist";

describe("Watchlist", () => {
  it("renders its header and the placeholder", () => {
    render(<Watchlist />);
    expect(screen.getByRole("heading", { name: "Watchlist" })).toBeInTheDocument();
    expect(screen.getByText(/watchlist coming soon/i)).toBeInTheDocument();
  });
});

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import NextFomc from "./next_fomc";

describe("NextFomc", () => {
  it("renders the header and the placeholder FOMC details", () => {
    render(<NextFomc />);
    expect(screen.getByRole("heading", { name: /next fomc/i })).toBeInTheDocument();
    expect(screen.getByText("27d")).toBeInTheDocument();
    expect(screen.getByText(/35 bp cut · 62%/)).toBeInTheDocument();
    expect(screen.getByText(/implied path: -68 bp by year-end/i)).toBeInTheDocument();
  });
});

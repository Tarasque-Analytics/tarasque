import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import MacroAiOverview from "./macro_ai_overview";

describe("MacroAiOverview", () => {
  it("renders its header and the placeholder", () => {
    render(<MacroAiOverview />);
    expect(screen.getByRole("heading", { name: "Macro AI overview" })).toBeInTheDocument();
    expect(screen.getByText(/ai overview coming soon/i)).toBeInTheDocument();
  });
});

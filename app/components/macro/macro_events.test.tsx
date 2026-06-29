import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import MacroEvents from "./macro_events";

describe("MacroEvents", () => {
  it("renders its header and the placeholder", () => {
    render(<MacroEvents />);
    expect(screen.getByRole("heading", { name: "Fed / macro events" })).toBeInTheDocument();
    expect(screen.getByText(/macro events coming soon/i)).toBeInTheDocument();
  });
});

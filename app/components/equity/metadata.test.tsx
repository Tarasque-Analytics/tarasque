import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import EquityMetaData from "./metadata";
import { makeEquityPayload, renderWithEquity } from "~/test/equity-test-utils";

describe("EquityMetaData", () => {
  it("renders the metadata sections and the security's sector", () => {
    renderWithEquity(<EquityMetaData />, makeEquityPayload());
    expect(screen.getByText("Equity Classes")).toBeInTheDocument();
    expect(screen.getByText("Reference")).toBeInTheDocument();
    expect(screen.getByText("Information Technology")).toBeInTheDocument();
  });

  it("renders nothing when the equity payload is unavailable", () => {
    const { container } = render(<EquityMetaData />);
    expect(container).toBeEmptyDOMElement();
  });
});

import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { EquityDataProvider } from "~/context/EquityDataContext";
import type { EquitiesPayload } from "~/utils/database";

// Shared helpers for the /equity/:symbol section-component tests.
//
// These tests are deliberately "application-side" only: they assert a component mounts and renders
// its expected structure / empty states, NOT specific financial values (those calc/display paths
// change often and would make the tests brittle). So the payload below carries empty data arrays —
// every section falls through to its no-data placeholder — except `security`, which metadata reads.

/** A fully-typed EquitiesPayload with empty data; override just the slice a test needs. */
export function makeEquityPayload(overrides: Partial<EquitiesPayload> = {}): EquitiesPayload {
  return {
    symbol: "AAPL",
    security: {
      security_id: 320193,
      ticker: "AAPL",
      company_name: "Apple Inc.",
      gics_sector: "Information Technology",
      gics_industry: "Software & Services",
      gics_subindustry: "Application Software",
      sector_etf: "XLK",
    },
    volatility_history: [],
    price_history: [],
    options_chain: [],
    ai_overview: null,
    latest_shap_snapshot: [],
    distribution_data: [],
    events: [],
    ...overrides,
  };
}

/** Render a component inside EquityDataProvider with a (minimal by default) payload. */
export function renderWithEquity(ui: ReactElement, payload: EquitiesPayload = makeEquityPayload()) {
  return render(<EquityDataProvider data={payload}>{ui}</EquityDataProvider>);
}

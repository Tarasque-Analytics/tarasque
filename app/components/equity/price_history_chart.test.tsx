import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import PriceHistoryChart, { computeSelectionStats } from "./price_history_chart";
import type { PriceRecord } from "~/utils/database";
import { makeEquityPayload, renderWithEquity } from "~/test/equity-test-utils";

describe("PriceHistoryChart", () => {
  it("shows the unavailable placeholder when no equity data is provided", () => {
    render(<PriceHistoryChart />);
    expect(screen.getByText(/price data is currently unavailable/i)).toBeInTheDocument();
  });

  it("shows the no-data placeholder when price history is empty", () => {
    renderWithEquity(<PriceHistoryChart />, makeEquityPayload({ price_history: [] }));
    expect(screen.getByText(/no price history available for AAPL/i)).toBeInTheDocument();
  });
});

/** Minimal PriceRecord — the selection helper only reads `date` and `close`. */
const row = (date: string, close: number): PriceRecord => ({
  date,
  open: null,
  high: null,
  low: null,
  close,
  adj_close: null,
  volume: null,
});

const ROWS: PriceRecord[] = [
  row("2026-01-12", 100),
  row("2026-02-02", 120),
  row("2026-03-01", 90),
  row("2026-04-01", 73.72),
];

describe("computeSelectionStats", () => {
  it("returns null for an empty rows array", () => {
    expect(computeSelectionStats([], 0, 0)).toBeNull();
  });

  it("computes a signed up move close-to-close over the window", () => {
    const s = computeSelectionStats(ROWS, 0, 1)!;
    expect(s.startDate).toBe("2026-01-12");
    expect(s.endDate).toBe("2026-02-02");
    expect(s.startClose).toBe(100);
    expect(s.endClose).toBe(120);
    expect(s.absChange).toBe(20);
    expect(s.pctChange).toBeCloseTo(20, 5);
    expect(s.up).toBe(true);
  });

  it("computes a signed down move with a negative change and direction", () => {
    const s = computeSelectionStats(ROWS, 0, 3)!;
    expect(s.startClose).toBe(100);
    expect(s.endClose).toBe(73.72);
    expect(s.absChange).toBeCloseTo(-26.28, 5);
    expect(s.pctChange).toBeCloseTo(-26.28, 5);
    expect(s.up).toBe(false);
    expect(s.startDate).toBe("2026-01-12");
    expect(s.endDate).toBe("2026-04-01");
  });

  it("normalizes order regardless of drag direction", () => {
    expect(computeSelectionStats(ROWS, 3, 0)).toEqual(computeSelectionStats(ROWS, 0, 3));
  });

  it("treats a single-point window as a flat (zero) change, direction up", () => {
    const s = computeSelectionStats(ROWS, 2, 2)!;
    expect(s.startDate).toBe("2026-03-01");
    expect(s.endDate).toBe("2026-03-01");
    expect(s.absChange).toBe(0);
    expect(s.pctChange).toBe(0);
    expect(s.up).toBe(true);
  });

  it("treats a flat two-point window as zero change, direction up", () => {
    const flat = [row("2026-01-01", 50), row("2026-01-02", 50)];
    const s = computeSelectionStats(flat, 0, 1)!;
    expect(s.absChange).toBe(0);
    expect(s.pctChange).toBe(0);
    expect(s.up).toBe(true);
  });

  it("clamps out-of-range indices to the data bounds", () => {
    const s = computeSelectionStats(ROWS, -5, 99)!;
    expect(s.startDate).toBe("2026-01-12");
    expect(s.endDate).toBe("2026-04-01");
  });
});

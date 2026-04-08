"""
batch_backtest.py — Overnight batch runner for untested tickers.

Runs the full backtest pipeline in batches of N tickers (default 3),
with ticker-level parallelism within each batch. Handles data refresh
per batch so that vsurfd/OHLCV/compustat_meta are pulled for each set.

Usage (from project root):
    python -m model.pipeline.batch_backtest
    python -m model.pipeline.batch_backtest --batch-size 4
    python -m model.pipeline.batch_backtest --start-batch 5   # resume from batch 5
    python -m model.pipeline.batch_backtest --dry-run          # show batches without running
"""
import argparse
import os
import sys
import time
from pathlib import Path

# ── Tickers already tested (v1-v4 + 2026-04-06 session) ──────────────
ALREADY_TESTED = {
    "BA", "PG", "AAPL", "XOM", "JPM", "GS", "C", "CVX",
    "AMZN", "GOOGL", "MRK", "NEE", "JNJ", "NVDA",
    # v4 partial (incomplete — re-running to get clean results):
    "WMT", "CAT", "MS", "LIN",
}

# ── Full 100-ticker universe (from config.py / claude_context.md) ─────
FULL_UNIVERSE = [
    # Tech
    "AAPL", "MSFT", "NVDA", "AMD", "ORCL", "INTC", "QCOM", "AVGO",
    "TXN", "IBM", "CRM", "ADBE", "AMAT", "MU", "CSCO",
    # Comm
    "GOOGL", "META", "NFLX", "DIS", "CMCSA", "T", "VZ",
    # ConsDisc
    "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "TGT", "LOW",
    "BKNG", "GM", "F",
    # ConsStap
    "PG", "KO", "PEP", "WMT", "COST", "PM", "MO", "CL",
    # Fin
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "AXP", "SCHW", "USB",
    # Health
    "JNJ", "LLY", "ABBV", "MRK", "PFE", "UNH", "TMO", "ABT",
    "BMY", "AMGN", "GILD", "CVS",
    # Indust
    "CAT", "HON", "BA", "UPS", "RTX", "DE", "MMM", "GE", "LMT", "NOC", "FDX",
    # Energy
    "XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "OXY",
    # Materials
    "LIN", "APD", "NEM", "FCX", "DOW",
    # Utilities
    "NEE", "DUK", "SO", "D", "AEP",
    # RealEstate
    "AMT", "PLD", "CCI", "EQIX", "SPG",
]


def get_untested_tickers():
    """Return tickers from the full universe that haven't been tested yet."""
    return [t for t in FULL_UNIVERSE if t not in ALREADY_TESTED]


def batch_list(items, size):
    """Split a list into batches of the given size."""
    return [items[i:i + size] for i in range(0, len(items), size)]


def run_batch(batch_idx, tickers, total_batches):
    """Run one batch: refresh data for these tickers, then backtest."""
    from .config import load_config
    from .data_loader import fetch_dataset
    from .backtest import BacktestEngine

    print(f"\n{'#'*60}")
    print(f"  BATCH {batch_idx + 1}/{total_batches}: {', '.join(tickers)}")
    print(f"{'#'*60}\n")

    dc, mc, bc = load_config()
    dc.tickers = tickers

    # Step 1: Ensure data is available for these tickers
    print(f"[BATCH] Fetching data for {tickers}...")
    batch_start = time.time()
    try:
        raw_data = fetch_dataset(dc, force_refresh=False)
    except Exception as e:
        print(f"[BATCH ERROR] Data fetch failed: {e}")
        return None

    # Step 2: Run backtest
    print(f"[BATCH] Starting backtest for {tickers}...")
    engine = BacktestEngine(dc, mc, bc)
    try:
        results = engine.run_sector_sweep(raw_data)
    except Exception as e:
        print(f"[BATCH ERROR] Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        return None

    elapsed = time.time() - batch_start
    print(f"\n[BATCH] Batch {batch_idx + 1} complete in {elapsed/60:.1f} min")

    if not results.empty:
        print(results[["ticker", "horizon", "rmse", "mz_beta", "mz_r2"]].to_string(index=False))

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Overnight batch backtest for untested tickers",
    )
    parser.add_argument(
        "--batch-size", type=int, default=3,
        help="Tickers per batch (default: 3, matching parallel_tickers config)",
    )
    parser.add_argument(
        "--start-batch", type=int, default=0,
        help="Resume from this batch number (0-indexed, default: 0)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show batch plan without running",
    )
    args = parser.parse_args()

    untested = get_untested_tickers()
    batches = batch_list(untested, args.batch_size)

    print(f"Untested tickers: {len(untested)}")
    print(f"Batch size: {args.batch_size}")
    print(f"Total batches: {len(batches)}")
    print()

    for i, batch in enumerate(batches):
        marker = ">>>" if i >= args.start_batch else "   "
        print(f"  {marker} Batch {i + 1}: {', '.join(batch)}")

    if args.dry_run:
        print("\n[DRY RUN] No backtests executed.")
        return

    print(f"\nStarting from batch {args.start_batch + 1}...")
    overall_start = time.time()

    for i in range(args.start_batch, len(batches)):
        run_batch(i, batches[i], len(batches))

    total_time = time.time() - overall_start
    print(f"\n{'='*60}")
    print(f"  ALL BATCHES COMPLETE — {total_time/3600:.1f} hours total")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

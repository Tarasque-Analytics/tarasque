"""
pull_all_data.py — Incremental data pull for all tickers in the universe.

Checks which tickers are already cached in vsurfd/ohlcv/compustat_meta and
only pulls missing ones from WRDS.  Appends new data to existing parquet
partitions without deleting what's already there.

Run this FIRST on Windows (where wrds is installed), then run batch_backtest.py.

Usage (from project root, on Windows):
    python -m model.pipeline.pull_all_data
    python -m model.pipeline.pull_all_data --force   # re-pull everything
"""
import argparse
import os
from pathlib import Path

import pandas as pd

from .config import load_config
from .data_loader import ParquetStore, WRDSLoader, fetch_dataset
from .batch_backtest import FULL_UNIVERSE


def get_cached_tickers(store: ParquetStore, data_type: str) -> set:
    """Return set of tickers already in a partitioned parquet store."""
    path = store._path(data_type)
    if not path.exists():
        return set()
    cached = set()
    for d in path.iterdir():
        if d.is_dir() and d.name.startswith("ticker="):
            cached.add(d.name.split("=", 1)[1])
    return cached


def pull_missing_vsurfd(loader: WRDSLoader, store: ParquetStore, all_tickers: list):
    """Pull vsurfd for tickers not yet in the cache, append to store."""
    cached = get_cached_tickers(store, "vsurfd")
    missing = [t for t in all_tickers if t not in cached]

    if not missing:
        print(f"[VSURFD] All {len(all_tickers)} tickers already cached.")
        return

    print(f"[VSURFD] {len(cached)} cached, {len(missing)} missing: {', '.join(missing[:10])}{'...' if len(missing) > 10 else ''}")
    print(f"[VSURFD] Pulling {len(missing)} tickers from WRDS (this is the slow part)...")

    df = loader.fetch_vsurfd(tickers=missing)
    if df.empty:
        print("[VSURFD] WARNING: No data returned from WRDS for missing tickers.")
        return

    # Append to existing partitioned store without deleting existing data
    path = store._path("vsurfd")
    path.mkdir(parents=True, exist_ok=True)
    df.to_parquet(
        path, engine="pyarrow", compression="snappy",
        partition_cols=["ticker"], index=False,
    )
    print(f"[VSURFD] Appended {len(df):,} rows for {df['ticker'].nunique()} tickers")


def pull_missing_ohlcv(loader: WRDSLoader, store: ParquetStore, all_tickers: list, factor_etfs: list):
    """Pull OHLCV for tickers not yet in the cache."""
    cached = get_cached_tickers(store, "ohlcv")
    all_needed = list(set(all_tickers + factor_etfs))
    missing = [t for t in all_needed if t not in cached]

    if not missing:
        print(f"[OHLCV] All {len(all_needed)} tickers already cached.")
        return

    print(f"[OHLCV] {len(cached)} cached, {len(missing)} missing: {', '.join(missing[:10])}{'...' if len(missing) > 10 else ''}")
    print(f"[OHLCV] Pulling {len(missing)} tickers from CRSP...")

    df = loader.fetch_crsp_daily(tickers=missing)
    if df.empty:
        print("[OHLCV] WARNING: No data returned from WRDS.")
        return

    path = store._path("ohlcv")
    path.mkdir(parents=True, exist_ok=True)
    df.to_parquet(
        path, engine="pyarrow", compression="snappy",
        partition_cols=["ticker"], index=False,
    )
    print(f"[OHLCV] Appended {len(df):,} rows for {df['ticker'].nunique()} tickers")


def pull_compustat_meta(loader: WRDSLoader, store: ParquetStore, all_tickers: list):
    """Re-pull compustat meta for all tickers (small, fast — always refresh)."""
    print(f"[COMPUSTAT] Pulling GICS sectors for {len(all_tickers)} tickers...")
    df = loader.fetch_compustat_meta(tickers=all_tickers)
    if df.empty:
        print("[COMPUSTAT] WARNING: No data returned.")
        return
    store.save(df, "compustat_meta")
    print(f"[COMPUSTAT] Saved {len(df)} rows")


def main():
    parser = argparse.ArgumentParser(description="Incremental data pull for full ticker universe")
    parser.add_argument("--force", action="store_true", help="Force re-pull everything")
    args = parser.parse_args()

    dc, mc, bc = load_config()

    # All tickers we need data for
    all_tickers = list(set(FULL_UNIVERSE))
    dc.tickers = all_tickers

    store = ParquetStore(dc.base_dir)
    loader = WRDSLoader(dc)

    print(f"Target: {len(all_tickers)} tickers")
    print(f"Cache dir: {dc.base_dir.resolve()}\n")

    try:
        if args.force:
            print("[FORCE] Re-pulling all data...\n")
            fetch_dataset(dc, force_refresh=True)
        else:
            # ── Incremental pulls ────────────────────────────────────
            # 1. OHLCV (CRSP) — partitioned by ticker
            pull_missing_ohlcv(loader, store, all_tickers, dc.all_factor_etfs)

            # 2. vsurfd (OptionMetrics) — partitioned by ticker, SLOW
            pull_missing_vsurfd(loader, store, all_tickers)

            # 3. Compustat meta — small, always refresh for all tickers
            pull_compustat_meta(loader, store, all_tickers)

            # 4. FRED / events / crsp_index — not ticker-partitioned,
            #    use standard fetch_dataset which skips if exists
            print("\n[FRED/EVENTS] Checking non-ticker data...")
            fetch_dataset(dc, include_options=False, force_refresh=False)
    finally:
        loader.close()

    # ── Summary ──────────────────────────────────────────────────────
    print(f"\n{'='*50}")
    print("  DATA PULL COMPLETE — Cache summary:")
    print(f"{'='*50}")
    for data_type in ["ohlcv", "vsurfd", "compustat_meta", "fred", "events/earnings", "crsp_index"]:
        cached = get_cached_tickers(store, data_type)
        if cached:
            print(f"  {data_type:20s}: {len(cached)} tickers")
        else:
            path = store._path(data_type)
            if path.exists() and any(path.rglob("*.parquet")):
                df = store.load(data_type)
                print(f"  {data_type:20s}: {len(df):,} rows")
            else:
                print(f"  {data_type:20s}: (empty)")

    print(f"\nYou can now run the batch backtest:")
    print(f"  python -m model.pipeline.batch_backtest")


if __name__ == "__main__":
    main()

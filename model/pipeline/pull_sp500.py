"""
pull_sp500.py — Bulk-pull WRDS data for the current S&P 500 universe.

TIME-SENSITIVE: WRDS access expires soon. Run this on the rig with WRDS
installed and a fat data drive (D:/Tarasque_DB). Expected runtime:

    Phase 1 — OHLCV + Compustat metadata     ~1.5 hours
    Phase 2 — OptionMetrics vsurfd           ~6-8 hours
    Phase 3 — OptionMetrics open interest    ~2-3 hours
    Phase 4 — Alpaca continuation splice     ~5 min

Total: ~10-12 hours. Run overnight.

Usage:
    # Full pull (recommended — start this tonight, walk away):
    python -m model.pipeline.pull_sp500 --all

    # Phased pull — useful if you want to commit OHLCV first then run vsurfd:
    python -m model.pipeline.pull_sp500 --phase 1
    python -m model.pipeline.pull_sp500 --phase 2
    python -m model.pipeline.pull_sp500 --phase 3
    python -m model.pipeline.pull_sp500 --phase 4

    # Just show the planned universe and exit:
    python -m model.pipeline.pull_sp500 --plan

The current production universe (91 tickers) is preserved — this script
expands the universe to ~500 names by adding net-new S&P 500 constituents.
Existing parquet partitions for the 91 active tickers are NOT re-fetched
unless --force-refresh is passed.
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path
from typing import List

import pandas as pd

from .config import load_config
from .data_loader import (
    WRDSLoader, ParquetStore,
    fetch_dataset, append_recent_data,
)


SP500_URL = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'


def fetch_sp500_universe() -> List[str]:
    """Scrape the current S&P 500 constituents from Wikipedia.
    Returns ticker symbols normalized for WRDS (period notation: BRK.B not BRK-B).

    Wikipedia blocks pandas' default User-Agent, so we fetch via requests
    with a real browser UA and feed the HTML into pandas."""
    import requests
    print(f'[universe] Fetching S&P 500 constituents from {SP500_URL}...')
    try:
        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0 Safari/537.36'
            )
        }
        resp = requests.get(SP500_URL, headers=headers, timeout=30)
        resp.raise_for_status()
        from io import StringIO
        tables = pd.read_html(StringIO(resp.text))
    except Exception as e:
        raise RuntimeError(f'Failed to fetch S&P 500 list: {e}\n'
                           f'Check internet connection or use --tickers-file.')

    sp500 = tables[0]
    # Wikipedia column name has shifted historically; handle both
    sym_col = 'Symbol' if 'Symbol' in sp500.columns else 'Ticker symbol'
    tickers = sp500[sym_col].astype(str).str.strip().tolist()

    # Wikipedia uses BRK.B style (matches WRDS). yfinance uses BRK-B.
    # Strip any leading/trailing whitespace, sort, dedup.
    tickers = sorted(set(t for t in tickers if t and not t.startswith('#')))
    print(f'[universe] Fetched {len(tickers)} S&P 500 constituents')
    return tickers


def merge_universe(sp500: List[str], existing: List[str]) -> List[str]:
    """Union of S&P 500 + currently-configured tickers. Preserves any tickers
    that are no longer in the index but we still want for historical continuity
    (e.g., LIN, OXY, VZ, META — excluded but we keep history)."""
    combined = sorted(set(sp500 + existing))
    print(f'[universe] S&P 500: {len(sp500)} | Existing: {len(existing)} | '
          f'Union: {len(combined)}')
    return combined


def report_what_is_cached(store: ParquetStore, tickers: List[str]):
    """Show what data already exists in cache vs. what's new."""
    print('\n[cache] Inventory of existing parquet partitions:')
    for data_type in ['ohlcv', 'vsurfd', 'oi_25delta', 'earnings', 'dividends', 'compustat_meta']:
        if store.exists(data_type):
            try:
                df = store.load(data_type)
                rows = len(df) if hasattr(df, '__len__') else 0
                if 'ticker' in df.columns:
                    n_tickers = df['ticker'].nunique()
                    print(f'  {data_type:18s}: {rows:>10,} rows | {n_tickers:>4} tickers')
                else:
                    print(f'  {data_type:18s}: {rows:>10,} rows')
            except Exception as e:
                print(f'  {data_type:18s}: error reading ({e})')
        else:
            print(f'  {data_type:18s}: NOT CACHED')


def phase_1_ohlcv_and_metadata(dc, force_refresh: bool = False):
    """Phase 1: OHLCV + Compustat metadata + earnings + dividends.
    Fastest, most reusable, can't be reproduced from any other source."""
    print('\n' + '=' * 72)
    print('PHASE 1 — OHLCV + Compustat metadata + earnings + dividends')
    print('  ~1.5 hours expected')
    print('=' * 72)

    loader = WRDSLoader(dc)
    store = ParquetStore(dc.base_dir)

    t0 = time.time()

    # OHLCV — call directly to skip the vsurfd/OI work in fetch_dataset
    if force_refresh or not store.exists('ohlcv'):
        df = loader.fetch_crsp_daily()
        if not df.empty:
            store.save(df, 'ohlcv', partition_cols=['ticker'])
            print(f'[phase 1] ohlcv saved: {len(df):,} rows')

    # Compustat metadata
    if force_refresh or not store.exists('compustat_meta'):
        df = loader.fetch_compustat_meta()
        if not df.empty:
            store.save(df, 'compustat_meta')
            print(f'[phase 1] compustat_meta saved: {len(df):,} rows')

    # Earnings
    if force_refresh or not store.exists('earnings'):
        df = loader.fetch_earnings_dates()
        if not df.empty:
            store.save(df, 'earnings')
            print(f'[phase 1] earnings saved: {len(df):,} rows')

    # Dividends
    if force_refresh or not store.exists('dividends'):
        df = loader.fetch_dividend_dates()
        if not df.empty:
            store.save(df, 'dividends')
            print(f'[phase 1] dividends saved: {len(df):,} rows')

    # CRSP index for benchmark
    if force_refresh or not store.exists('crsp_index'):
        df = loader.fetch_crsp_index()
        if not df.empty:
            store.save(df, 'crsp_index')
            print(f'[phase 1] crsp_index saved: {len(df):,} rows')

    print(f'\n[phase 1] DONE in {(time.time() - t0) / 60:.1f} min')


def phase_2_vsurfd(dc, force_refresh: bool = False):
    """Phase 2: OptionMetrics volatility surface. The expensive one."""
    print('\n' + '=' * 72)
    print('PHASE 2 — OptionMetrics vsurfd (volatility surface)')
    print('  ~6-8 hours expected (year tables 2014-2025)')
    print('=' * 72)

    loader = WRDSLoader(dc)
    store = ParquetStore(dc.base_dir)

    t0 = time.time()
    if force_refresh or not store.exists('vsurfd'):
        df = loader.fetch_vsurfd()
        if not df.empty:
            store.save(df, 'vsurfd', partition_cols=['ticker'])
            print(f'[phase 2] vsurfd saved: {len(df):,} rows')

    print(f'\n[phase 2] DONE in {(time.time() - t0) / 60:.1f} min')


def phase_3_oi(dc, force_refresh: bool = False):
    """Phase 3: OptionMetrics open interest at 25-delta."""
    print('\n' + '=' * 72)
    print('PHASE 3 — OptionMetrics open interest (25-delta)')
    print('  ~2-3 hours expected')
    print('=' * 72)

    loader = WRDSLoader(dc)
    store = ParquetStore(dc.base_dir)

    t0 = time.time()
    if force_refresh or not store.exists('oi_25delta'):
        df = loader.fetch_oi_25delta()
        if not df.empty:
            store.save(df, 'oi_25delta', partition_cols=['ticker'])
            print(f'[phase 3] oi_25delta saved: {len(df):,} rows')

    print(f'\n[phase 3] DONE in {(time.time() - t0) / 60:.1f} min')


def phase_4_alpaca_splice(dc):
    """Phase 4: Splice Alpaca data onto the tail of the CRSP OHLCV.
    Extends coverage past CRSP cutoff (typically end of last year)."""
    print('\n' + '=' * 72)
    print('PHASE 4 — Alpaca continuation splice')
    print('  ~5 min — extends OHLCV past CRSP cutoff')
    print('=' * 72)

    t0 = time.time()

    # Read what we have, splice on Alpaca tail
    raw_data = fetch_dataset(dc, force_refresh=False)
    raw_data = append_recent_data(dc, raw_data)

    # Re-save the spliced OHLCV
    store = ParquetStore(dc.base_dir)
    if 'ohlcv' in raw_data and not raw_data['ohlcv'].empty:
        store.save(raw_data['ohlcv'], 'ohlcv', partition_cols=['ticker'])
        max_date = raw_data['ohlcv']['date'].max()
        print(f'[phase 4] OHLCV extended to {max_date}, {len(raw_data["ohlcv"]):,} rows')

    print(f'\n[phase 4] DONE in {(time.time() - t0) / 60:.1f} min')


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--all', action='store_true',
                   help='Run all 4 phases sequentially (recommended overnight job)')
    p.add_argument('--phase', type=int, choices=[1, 2, 3, 4],
                   help='Run a specific phase only')
    p.add_argument('--plan', action='store_true',
                   help='Just print the universe + cache inventory, no fetches')
    p.add_argument('--force-refresh', action='store_true',
                   help='Re-fetch even if parquet exists (DANGEROUS — use only for known stale data)')
    p.add_argument('--tickers-file',
                   help='Optional path to a newline-delimited ticker file instead of Wikipedia')
    args = p.parse_args()

    # ── Build the expanded universe ──────────────────────────────────────
    dc, mc, bc = load_config()
    existing = list(dc.tickers)

    if args.tickers_file:
        sp500 = Path(args.tickers_file).read_text().strip().split('\n')
        sp500 = [t.strip() for t in sp500 if t.strip()]
        print(f'[universe] Loaded {len(sp500)} tickers from {args.tickers_file}')
    else:
        sp500 = fetch_sp500_universe()

    expanded = merge_universe(sp500, existing)
    dc.tickers = expanded

    print(f'\n[universe] Final pull universe: {len(expanded)} tickers')
    print(f'[universe] Net-new vs existing config: {len(set(sp500) - set(existing))}')
    print(f'[universe] Plus {len(dc.all_factor_etfs)} factor ETFs')

    store = ParquetStore(dc.base_dir)
    report_what_is_cached(store, expanded)

    if args.plan:
        print('\n[plan] --plan flag: exiting without fetching anything.')
        return

    # ── Execute phases ───────────────────────────────────────────────────
    if not args.all and args.phase is None:
        print('\nNo action specified. Use --all (overnight) or --phase N (single phase).')
        p.print_help()
        sys.exit(1)

    total_start = time.time()

    phases_to_run = [1, 2, 3, 4] if args.all else [args.phase]

    for phase in phases_to_run:
        if phase == 1:
            phase_1_ohlcv_and_metadata(dc, force_refresh=args.force_refresh)
        elif phase == 2:
            phase_2_vsurfd(dc, force_refresh=args.force_refresh)
        elif phase == 3:
            phase_3_oi(dc, force_refresh=args.force_refresh)
        elif phase == 4:
            phase_4_alpaca_splice(dc)

    elapsed = (time.time() - total_start) / 60
    print(f'\n{"=" * 72}')
    print(f'ALL DONE — total elapsed: {elapsed:.1f} min ({elapsed/60:.1f} hours)')
    print(f'{"=" * 72}')
    report_what_is_cached(store, expanded)


if __name__ == '__main__':
    main()
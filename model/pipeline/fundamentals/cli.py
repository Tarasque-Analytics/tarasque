"""
cli.py — Backfill the RAFI divergence series for the S&P 500 corpus.

Reads the SP500 ticker → CIK map from automation/data/sp500.csv (managed by
the lead-dev's automation.tools.sync_sp500). For each ticker:
  1. Fetch (or read from cache) the EDGAR XBRL Company Facts blob.
  2. Load OHLCV from the local Parquet cache (model-corpus tickers + sector
     ETFs are covered; the remaining ~400 SP500 names get logged + skipped
     until a price-spine ingest fills them in).
  3. Run the full divergence pipeline.
  4. Write per-ticker CSV to data_cache/sec_fundamentals/divergence/.
  5. Concat all rows into a single corpus frame for Supabase upsert.

Usage:
    python -m model.pipeline.fundamentals.cli --all
    python -m model.pipeline.fundamentals.cli --tickers CVX XOM MSFT
    python -m model.pipeline.fundamentals.cli --tickers CVX --refresh-xbrl
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .divergence import CANONICAL_DATE, compute_divergence_for_firm
from .edgar_xbrl import EdgarXbrlClient, EdgarXbrlError


REPO_ROOT = Path(__file__).resolve().parents[3]
SP500_CSV = REPO_ROOT / 'automation' / 'data' / 'sp500.csv'
OUT_DIR = REPO_ROOT / 'data_cache' / 'sec_fundamentals' / 'divergence'


def load_sp500_universe() -> pd.DataFrame:
    """Load ticker → CIK mapping from the automation/ folder's curated list."""
    if not SP500_CSV.exists():
        raise FileNotFoundError(
            f'SP500 list not found at {SP500_CSV}. Run '
            '`python -m automation.tools.sync_sp500 --refresh` to rebuild.'
        )
    df = pd.read_csv(SP500_CSV)
    if 'ticker' not in df.columns or 'cik' not in df.columns:
        raise ValueError(f'sp500.csv missing required columns. Got {list(df.columns)}.')
    df['cik'] = pd.to_numeric(df['cik'], errors='coerce').astype('Int64')
    df = df.dropna(subset=['cik']).copy()
    df['cik'] = df['cik'].astype(int)
    return df[['ticker', 'cik', 'company_name', 'gics_sector']].reset_index(drop=True)


def load_prices_for_ticker(ticker: str) -> Optional[pd.DataFrame]:
    """Pull adj_close daily series for one ticker from the OHLCV parquet cache.

    Returns None if not in cache (caller logs + skips). The full SP500 will
    need a separate price-spine ingest for the ~400 names not in our model
    corpus.
    """
    from ..config import load_config
    from ..data_loader import ParquetStore

    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    try:
        df = store.load('ohlcv', tickers=[ticker]).copy()
    except Exception:
        return None
    if df.empty:
        return None

    df['date'] = pd.to_datetime(df['date'], format='mixed', errors='coerce')
    df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)

    # Reconstruct adj_close from CRSP ret (split + dividend adjusted), matching
    # export_for_webapp.py's v6 methodology. Falls back to close.pct_change if
    # ret is missing (Alpaca-appended rows).
    if 'prc' in df.columns:
        df['close'] = df['prc'].abs()
    elif 'close' in df.columns:
        df['close'] = df['close'].abs()
    else:
        return None

    if 'ret' in df.columns and df['ret'].notna().any():
        rets = df['ret'].copy()
        fallback = df['close'].pct_change()
        rets = rets.where(rets.notna(), fallback).fillna(0.0)
        cum = (1.0 + rets).cumprod()
        last_close = float(df['close'].iloc[-1])
        df['adj_close'] = cum * (last_close / float(cum.iloc[-1]))
    else:
        df['adj_close'] = df['close']

    return df[['date', 'adj_close']].dropna()


def backfill_one(ticker: str, cik: int, client: EdgarXbrlClient,
                  refresh_xbrl: bool = False, out_dir: Path = OUT_DIR) -> dict:
    """Run the full pipeline for one ticker. Returns a status dict."""
    out_dir.mkdir(parents=True, exist_ok=True)
    status = {'ticker': ticker, 'cik': cik}

    prices = load_prices_for_ticker(ticker)
    if prices is None or prices.empty:
        status['status'] = 'no_prices'
        return status

    try:
        blob = client.cached_get(cik, force=refresh_xbrl)
    except EdgarXbrlError as e:
        status['status'] = 'xbrl_fail'
        status['error'] = str(e)
        return status

    try:
        result = compute_divergence_for_firm(blob, prices, canonical_date=CANONICAL_DATE)
    except Exception as e:
        status['status'] = 'pipeline_fail'
        status['error'] = str(e)
        return status

    result = result[result['date'] >= pd.Timestamp('2014-01-01')].copy()
    result.insert(0, 'ticker', ticker)
    result.insert(1, 'cik', cik)

    out_path = out_dir / f'{ticker}_divergence.csv'
    result.to_csv(out_path, index=False)

    div = result['divergence'].dropna()
    status.update({
        'status': 'ok',
        'rows': len(result),
        'div_min': float(div.min()) if not div.empty else None,
        'div_median': float(div.median()) if not div.empty else None,
        'div_max': float(div.max()) if not div.empty else None,
        'breaks': int(result.get('structural_break',
                                 pd.Series(dtype=bool)).fillna(False).sum()),
        'output': str(out_path.relative_to(REPO_ROOT)),
    })
    return status


def backfill_corpus(tickers: Optional[list] = None,
                     refresh_xbrl: bool = False) -> pd.DataFrame:
    """Backfill the full S&P 500 (or a subset if `tickers` given)."""
    universe = load_sp500_universe()
    if tickers:
        universe = universe[universe['ticker'].isin(tickers)]
        if universe.empty:
            print(f'[fundamentals] No matches in SP500 list for: {tickers}')
            return pd.DataFrame()

    print(f'[fundamentals] Backfilling {len(universe)} ticker(s)...\n')
    client = EdgarXbrlClient()
    results = []
    t0 = time.monotonic()
    for i, row in enumerate(universe.itertuples(index=False), start=1):
        status = backfill_one(row.ticker, int(row.cik), client,
                              refresh_xbrl=refresh_xbrl)
        results.append(status)
        if status['status'] == 'ok':
            med = status.get('div_median')
            med_str = f'{med:.3f}' if med is not None else 'all_nan'
            print(f'  [{i:>3}/{len(universe)}] {row.ticker:6s} ok  '
                  f'rows={status["rows"]:>5}  '
                  f'div median={med_str}  '
                  f'breaks={status["breaks"]}')
        else:
            print(f'  [{i:>3}/{len(universe)}] {row.ticker:6s} {status["status"]}'
                  f'{":" + status.get("error","")[:60] if status.get("error") else ""}')

    elapsed = time.monotonic() - t0
    print(f'\n[fundamentals] Done in {elapsed:.1f}s')
    summary = pd.DataFrame(results)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--tickers', nargs='*', default=None,
                   help='Subset of tickers (default: full SP500 list)')
    p.add_argument('--all', action='store_true',
                   help='Run the full universe (default behavior when no --tickers)')
    p.add_argument('--refresh-xbrl', action='store_true',
                   help='Force re-fetch from SEC instead of using cache')
    args = p.parse_args()

    if not args.tickers and not args.all:
        p.print_help()
        sys.exit(1)

    summary = backfill_corpus(tickers=args.tickers, refresh_xbrl=args.refresh_xbrl)
    if summary.empty:
        sys.exit(2)

    # Summarize by status
    counts = summary['status'].value_counts().to_dict()
    print('\nStatus counts:')
    for k, v in counts.items():
        print(f'  {k}: {v}')


if __name__ == '__main__':
    main()

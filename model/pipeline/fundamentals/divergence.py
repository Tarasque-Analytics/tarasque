"""
divergence.py — End-to-end per-firm divergence series.

Pipeline:
  1. Extract per-period fundamentals from EDGAR XBRL (xbrl_extract).
  2. Compute per-share legs + smooth cyclical legs (ttm_smooth).
  3. As-of project quarterly legs onto a daily price spine (filing-date anchor).
  4. Index legs at canonical base + equal-weight composite (composite).
  5. price_index(t)  = price(t) / price(canonical_date).
  6. divergence(t)   = price_index(t) / rafi_composite(t).
  7. Flag structural breaks (M&A) for the UI to surface.

The output is one row per calendar date per firm:
    date, divergence, rafi_composite, price, price_index,
    rev_ps_smoothed, ocf_ps_smoothed, book_ps, dps, structural_break,
    n_legs_present, last_filing_date

Frontend re-zero (per spec):
    divergence_shown(t) = divergence(t) / divergence(user_start)
applied client-side. The stored `divergence` column is canonical-base.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .composite import LEGS, index_legs_and_composite
from .ttm_smooth import compute_per_share_legs, detect_structural_breaks
from .xbrl_extract import extract_facts


CANONICAL_DATE = pd.Timestamp('2014-01-02')


def asof_project_to_daily(per_period_legs: pd.DataFrame,
                            daily_dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Project quarterly per-period fundamentals onto a daily date spine via
    backward as-of join on `filed` date.

    Args:
      per_period_legs: output of compute_per_share_legs — one row per period_end
                        with 'filed', the 4 raw legs, and the 2 smoothed legs.
      daily_dates: the calendar to project onto (typically the price-spine dates).

    Returns:
      DataFrame with one row per date in daily_dates. Leg columns ffilled
      from the most-recent filing on/before each date. Also carries
      'last_filing_date' = the `filed` of that source row.
    """
    cols_to_carry = list(LEGS) + ['book_ps', 'dps', 'filed', 'period_end',
                                    'structural_break_flag']
    # Make sure these exist even if upstream skipped them
    df = per_period_legs.copy()
    if 'structural_break_flag' not in df.columns:
        df['structural_break_flag'] = False
    have = [c for c in cols_to_carry if c in df.columns]
    df = (
        df[have].dropna(subset=['filed'])
        # Sort by filed then period_end so merge_asof's backward direction
        # picks the LATEST PERIOD at a given filing date, not an older
        # restatement that happens to share the filed timestamp. A 10-K
        # filed Oct-Y1 publishes the current FY-end period AND comparatives
        # for prior years; we want the current period at the join.
        .sort_values(['filed', 'period_end'])
        .reset_index(drop=True)
    )

    spine = pd.DataFrame({'date': pd.to_datetime(daily_dates)}).sort_values('date').reset_index(drop=True)
    if df.empty:
        for c in have:
            spine[c] = np.nan
        spine['last_filing_date'] = pd.NaT
        return spine

    joined = pd.merge_asof(
        spine, df, left_on='date', right_on='filed', direction='backward',
    )
    joined = joined.rename(columns={'filed': 'last_filing_date'})

    # Structural break: event-only flag (True on the FIRST day a break-flagged
    # filing becomes active, False afterwards). Without this, the ffilled flag
    # stays True until the next filing — confusing for a "marker" UI.
    if 'structural_break_flag' in joined.columns:
        flag = joined['structural_break_flag'].fillna(False).astype(bool)
        first_day = joined['last_filing_date'] != joined['last_filing_date'].shift(1)
        joined['structural_break_flag'] = flag & first_day
    return joined


def compute_divergence_for_firm(
    blob: dict,
    prices: pd.DataFrame,
    canonical_date: pd.Timestamp = CANONICAL_DATE,
) -> pd.DataFrame:
    """Full pipeline: XBRL blob + prices -> daily divergence series.

    Args:
      blob: SEC company-facts JSON (from edgar_xbrl.company_facts).
      prices: DataFrame with columns ['date', 'adj_close']. Daily spine, ascending.
      canonical_date: the universe-wide 1.0 reference (default 2014-01-02).

    Returns:
      DataFrame (one row per date in `prices`) with columns:
        date, price, price_index, rafi_composite, divergence,
        rev_ps_smoothed, ocf_ps_smoothed, book_ps, dps,
        last_filing_date, structural_break, n_legs_present
    """
    facts = extract_facts(blob)
    if facts.empty:
        return _empty_divergence_frame(prices)
    facts = compute_per_share_legs(facts)
    facts['structural_break_flag'] = detect_structural_breaks(facts).values

    prices = prices.sort_values('date').reset_index(drop=True).copy()
    prices['date'] = pd.to_datetime(prices['date'])

    daily_legs = asof_project_to_daily(facts, prices['date'])
    indexed = index_legs_and_composite(daily_legs, canonical_date)

    # Price index: divide by adj_close at canonical_date (or nearest prior trading day).
    out = prices.merge(indexed, on='date', how='left')
    base_price_rows = out[out['date'] <= canonical_date]
    if base_price_rows.empty:
        out['price_index'] = np.nan
    else:
        base_price = float(base_price_rows['adj_close'].iloc[-1])
        out['price_index'] = out['adj_close'] / base_price if base_price else np.nan

    out['divergence'] = out['price_index'] / out['rafi_composite']
    out = out.rename(columns={
        'adj_close': 'price',
        'structural_break_flag': 'structural_break',
    })

    keep = [
        'date', 'price', 'price_index', 'rafi_composite', 'divergence',
        'rev_ps_smoothed', 'ocf_ps_smoothed', 'book_ps_smoothed', 'dps_smoothed',
        'book_ps', 'dps',  # raw kept for transparency
        'last_filing_date', 'structural_break', 'n_legs_present',
    ]
    keep = [c for c in keep if c in out.columns]
    return out[keep]


def _empty_divergence_frame(prices: pd.DataFrame) -> pd.DataFrame:
    out = prices[['date']].copy()
    for c in ('price', 'price_index', 'rafi_composite', 'divergence',
              'rev_ps_smoothed', 'ocf_ps_smoothed', 'book_ps', 'dps',
              'last_filing_date', 'structural_break', 'n_legs_present'):
        out[c] = np.nan if c not in ('structural_break',) else False
    return out


if __name__ == '__main__':
    import sys
    from .edgar_xbrl import company_facts
    from ..data_loader import ParquetStore
    from ..config import load_config

    cik = int(sys.argv[1]) if len(sys.argv) > 1 else 93410
    ticker = sys.argv[2] if len(sys.argv) > 2 else 'CVX'

    blob = company_facts(cik)
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    ohlcv = store.load('ohlcv', tickers=[ticker]).copy()
    ohlcv['date'] = pd.to_datetime(ohlcv['date'], format='mixed', errors='coerce')
    ohlcv = ohlcv.dropna(subset=['date']).sort_values('date').reset_index(drop=True)
    # Build adj_close from ret (same as export_for_webapp)
    if 'ret' in ohlcv.columns and ohlcv['ret'].notna().any():
        rets = ohlcv['ret'].copy()
        fallback = ohlcv['prc'].abs().pct_change() if 'prc' in ohlcv.columns else 0
        rets = rets.where(rets.notna(), fallback).fillna(0.0)
        cum = (1.0 + rets).cumprod()
        last_close = float(ohlcv['prc'].abs().iloc[-1])
        ohlcv['adj_close'] = cum * (last_close / float(cum.iloc[-1]))
    else:
        ohlcv['adj_close'] = ohlcv['prc'].abs() if 'prc' in ohlcv.columns else np.nan
    prices = ohlcv[['date', 'adj_close']]

    result = compute_divergence_for_firm(blob, prices)
    result_p = result[result['date'] >= pd.Timestamp('2014-01-01')].reset_index(drop=True)
    print(f'\n{blob.get("entityName")} — {len(result_p):,} daily rows '
          f'(canonical = {CANONICAL_DATE.date()})\n')

    print('First 3 rows (near canonical):')
    print(result_p.head(3)[['date', 'price', 'price_index', 'rafi_composite',
                              'divergence', 'n_legs_present']].to_string(index=False))
    print('\nLatest 3 rows:')
    print(result_p.tail(3)[['date', 'price', 'price_index', 'rafi_composite',
                              'divergence', 'n_legs_present']].to_string(index=False))

    # Summary stats
    div = result_p['divergence'].dropna()
    print(f'\nDivergence: min={div.min():.3f}  p25={div.quantile(0.25):.3f}  '
          f'median={div.median():.3f}  p75={div.quantile(0.75):.3f}  max={div.max():.3f}')
    print(f'Structural breaks: {int(result_p["structural_break"].fillna(False).sum())}')

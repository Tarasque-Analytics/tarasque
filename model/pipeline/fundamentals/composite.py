"""
composite.py — Canonical-base indexing + equal-weight RAFI composite.

Inputs: a daily-spine DataFrame with the 4 RAFI legs already projected onto
calendar dates via as-of join (divergence.py does the projection).

Math (per spec)
---------------
  indexed_leg(t) = leg(t) / leg(canonical_date)
  rafi(t)        = mean( indexed_leg_i(t) for i in {rev_ps_smoothed, ocf_ps_smoothed,
                                                      book_ps, dps} )

Canonical date is a FIXED modeling choice — same date for every firm in the
universe so cross-section comparison stays apples-to-apples. The frontend
re-zero (divergence(t) / divergence(user_pick)) is layered on top; it doesn't
change the composite.

The 4-leg average is equal-weight per spec. We use the SMOOTHED legs for rev_ps
and ocf_ps (cyclical noise damped by 20Q mean); RAW for book_ps and dps (stable
enough).

Canonical-date scarcity: firms without enough pre-history to have a valid
smoothed value at the canonical date will produce NaN — the divergence series
for that firm starts NaN and only begins once the smoothing converges. We
accept this (spec's "consistent across the universe" requirement) rather than
giving each firm its own canonical date.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# Order matters only for readability — the composite is a simple equal-weight mean.
LEGS = ('rev_ps_smoothed', 'ocf_ps_smoothed', 'book_ps', 'dps')


def _value_at_canonical(daily_legs: pd.DataFrame, canonical_date: pd.Timestamp,
                          col: str) -> float:
    """Take the leg value from the row at-or-just-before `canonical_date`.

    daily_legs is sorted ascending by 'date'. Returns NaN if no row exists
    on or before canonical_date, or if the column is NaN there.
    """
    eligible = daily_legs[daily_legs['date'] <= canonical_date]
    if eligible.empty:
        return float('nan')
    return float(eligible[col].iloc[-1]) if col in eligible.columns else float('nan')


def index_legs_and_composite(daily_legs: pd.DataFrame,
                              canonical_date: pd.Timestamp,
                              legs: tuple = LEGS) -> pd.DataFrame:
    """Index each leg to 1.0 at canonical_date, return frame + rafi column.

    Args:
      daily_legs: daily-frequency frame with a 'date' column + the 4 leg cols.
                   Must be sorted ascending by 'date'. Leg columns already
                   ffilled from quarterly fundamentals onto the daily spine.
      canonical_date: fixed modeling reference (e.g., pd.Timestamp('2014-01-02')).
      legs: tuple of leg-column names to include in the composite. Default is
            the spec's 4: (rev_ps_smoothed, ocf_ps_smoothed, book_ps, dps).

    Returns:
      A copy of daily_legs with these columns added:
        <leg>_indexed       for each leg, the indexed series
        rafi_composite      equal-weight mean of indexed legs (per row)
        n_legs_present      number of legs contributing to the mean at that row
                            (lets the consumer reject thin rows downstream)
    """
    df = daily_legs.sort_values('date').reset_index(drop=True).copy()

    for leg in legs:
        if leg not in df.columns:
            df[leg] = np.nan

    base_vals = {leg: _value_at_canonical(df, canonical_date, leg) for leg in legs}

    # Index each leg. Where the base is NaN, the leg's indexed series is NaN.
    indexed_cols = []
    for leg in legs:
        base = base_vals[leg]
        col = f'{leg}_indexed'
        if not np.isfinite(base) or base == 0:
            df[col] = np.nan
        else:
            df[col] = df[leg] / base
        indexed_cols.append(col)

    # Equal-weight composite: mean across the 4 indexed legs, skipping NaN.
    df['rafi_composite'] = df[indexed_cols].mean(axis=1, skipna=True)
    df['n_legs_present'] = df[indexed_cols].notna().sum(axis=1)

    return df


def canonical_base_values(daily_legs: pd.DataFrame,
                            canonical_date: pd.Timestamp,
                            legs: tuple = LEGS) -> dict:
    """Diagnostic: return the leg values used as the 1.0 reference."""
    return {leg: _value_at_canonical(daily_legs, canonical_date, leg) for leg in legs}

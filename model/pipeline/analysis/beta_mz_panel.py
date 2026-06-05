"""
beta_mz_panel.py -- Shared helper: the PER-TICKER weekly beta_mz panel.

compute_weekly_aggregate() (in beta_mz_deep_dive) collapses to the universe mean
and throws away the per-ticker detail. The robustness battery needs the panel
itself (random sub-ensembles, dispersion, etc.), so we compute it once and cache.

Long format: (ticker, asof, beta_mz). ~93 tickers x ~596 Fridays.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .beta_mz_deep_dive import RESULTS_DIR, ROLLING_BD_BMZ, beta_mz_at

CACHE = RESULTS_DIR / "validation" / "beta_mz_per_ticker_weekly.csv"


def compute_per_ticker_weekly() -> pd.DataFrame:
    rows = []
    for f in sorted(RESULTS_DIR.glob("predictions_*.csv")):
        ticker = f.stem.replace("predictions_", "")
        try:
            df = pd.read_csv(f, parse_dates=["date"],
                             usecols=["date", "y_true", "y_pred", "horizon"])
        except Exception:
            continue
        h21 = df[df["horizon"] == 21].drop(columns=["horizon"])
        if h21.empty or len(h21) < ROLLING_BD_BMZ + 20:
            continue
        first_valid = h21["date"].min() + pd.tseries.offsets.BDay(ROLLING_BD_BMZ)
        last_valid = h21["date"].max()
        for fr in pd.date_range(first_valid, last_valid, freq="W-FRI"):
            beta, _ = beta_mz_at(h21, fr)
            if np.isfinite(beta):
                rows.append({"ticker": ticker, "asof": fr, "beta_mz": beta})
    return pd.DataFrame(rows)


def load_per_ticker_weekly(force: bool = False) -> pd.DataFrame:
    if CACHE.exists() and not force:
        return pd.read_csv(CACHE, parse_dates=["asof"])
    panel = compute_per_ticker_weekly()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(CACHE, index=False)
    return panel


def aggregate_subset(panel: pd.DataFrame, tickers=None) -> pd.DataFrame:
    """Universe (or subset) weekly aggregate with mean + dispersion."""
    sub = panel if tickers is None else panel[panel["ticker"].isin(tickers)]
    agg = sub.groupby("asof").agg(
        mean_bmz=("beta_mz", "mean"),
        median_bmz=("beta_mz", "median"),
        std_bmz=("beta_mz", "std"),
        n_tickers=("beta_mz", "count"),
    ).reset_index().sort_values("asof").reset_index(drop=True)
    return agg


if __name__ == "__main__":
    p = load_per_ticker_weekly(force=True)
    print(f"per-ticker panel: {p.shape}, {p['ticker'].nunique()} tickers, "
          f"{p['asof'].nunique()} weeks -> {CACHE}")

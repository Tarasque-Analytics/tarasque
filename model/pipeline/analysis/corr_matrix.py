"""
corr_matrix.py — Pairwise return correlations across the ticker universe.

Inputs needed for portfolio aggregation in the web app:
  - Cross-ticker return correlation matrix (multiple lookback windows)
  - Per-ticker realized vol (from cached OHLCV, GK estimator)
These let the backend compute portfolio variance:
    sigma_p^2 = w' Sigma w
where Sigma_ij = corr_ij * sigma_i * sigma_j and (sigma_i, sigma_j) are the
per-ticker forecasts produced by `forecast --retrain`.

Three windows are written so the frontend can show both regime-specific
correlation (63d) and structural correlation (252d, 504d):
  - 63d: tactical / current-regime
  - 252d: 1-year structural
  - 504d: 2-year (covers a full cycle including 2020 + tariff regime)

Outputs:
  model/pipeline/results/corr_matrix_w63.csv
  model/pipeline/results/corr_matrix_w252.csv
  model/pipeline/results/corr_matrix_w504.csv
  model/pipeline/results/corr_summary.json (top correlated pairs, isolated names)

Run:
    python -m model.pipeline.analysis.corr_matrix
    python -m model.pipeline.analysis.corr_matrix --window 252       # one window
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import load_config
from ..data_loader import ParquetStore
from ..utils import DECIMAL_PRECISION, round_for_output


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "model" / "pipeline" / "results"
WINDOWS = (63, 252, 504)


def build_returns(closes: pd.DataFrame) -> pd.DataFrame:
    """Log returns from wide closes table; aligned on common dates."""
    return np.log(closes / closes.shift(1)).dropna(how="all")


def compute_corr(returns: pd.DataFrame, window: int) -> pd.DataFrame:
    """Final-window pairwise correlation matrix."""
    if len(returns) < window:
        raise ValueError(f"Need at least {window} rows; have {len(returns)}.")
    sub = returns.iloc[-window:]
    # drop columns that have insufficient data in this window
    sub = sub.loc[:, sub.notna().sum() >= int(0.8 * window)]
    return sub.corr(method="pearson")


def summarize(corr: pd.DataFrame, top_n: int = 25) -> dict:
    """Top correlated pairs (ex-self) and most-isolated tickers."""
    # Cast index/columns to plain strings (categorical comparisons fail otherwise)
    corr = corr.copy()
    corr.index = corr.index.astype(str)
    corr.columns = corr.columns.astype(str)
    # Stack to long, drop self-pairs and duplicates
    s = corr.stack()
    s.index.names = ["a", "b"]
    s = s[s.index.get_level_values("a") < s.index.get_level_values("b")]
    s = s.sort_values(ascending=False)

    top_pairs = (s.head(top_n).reset_index()
                 .rename(columns={0: "corr"}).to_dict("records"))
    bottom_pairs = (s.tail(top_n).reset_index()
                    .rename(columns={0: "corr"}).to_dict("records"))

    # Most isolated ticker = lowest mean off-diagonal correlation
    off_diag_mean = (corr.where(~np.eye(len(corr), dtype=bool))
                     .mean(axis=0).sort_values())
    isolated = (off_diag_mean.head(top_n).reset_index()
                .rename(columns={0: "mean_corr", "index": "ticker"})
                .to_dict("records"))

    return {
        "top_pairs": top_pairs,
        "bottom_pairs": bottom_pairs,
        "most_isolated_tickers": isolated,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=None,
                    help="Single lookback window in BDays (default: 63 + 252 + 504)")
    args = ap.parse_args()

    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    ohlcv = store.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    ohlcv = ohlcv.drop_duplicates(subset=["date", "ticker"], keep="last")
    closes = ohlcv.pivot(index="date", columns="ticker", values="prc").ffill()
    returns = build_returns(closes)

    windows = [args.window] if args.window else WINDOWS
    summary = {}

    for w in windows:
        corr = compute_corr(returns, w)
        out = RESULTS_DIR / f"corr_matrix_w{w}.csv"
        corr_rounded = round_for_output(corr.reset_index(), DECIMAL_PRECISION)
        # round_for_output uses a per-column schema; corr cells are not in the schema,
        # so round explicitly here.
        corr_round = corr.round(4)
        corr_round.to_csv(out)
        print(f"[CORR] Wrote {out.name} ({len(corr_round)} x {len(corr_round.columns)})")
        summary[f"w{w}"] = summarize(corr_round)

    out_json = RESULTS_DIR / "corr_summary.json"
    with open(out_json, "w") as f:
        json.dump(summary, f, indent=2, default=float)
    print(f"[CORR] Wrote summary {out_json.name}")


if __name__ == "__main__":
    main()

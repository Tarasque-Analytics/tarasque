"""
feature_decay.py — Detect when individual predictors lose information over time.

Inputs (produced by backtest.py):
    lasso_detailed_{ticker}.csv          per-step Lasso coefficient trajectory
    xgb_importance_steps_{ticker}.csv    per-step XGB feature importance

Outputs:
    feature_decay_{ticker}.csv           per-(horizon × feature) decay metrics
    feature_decay_summary.csv            corpus-level rollup (when --all)

Metrics
-------
rolling_inclusion_freq
    Lasso fraction of fits with non-zero coef inside an 8-step sliding window
    (~32 trading weeks at the 20-BDay cadence). Reported as the *latest*
    rolling value plus the peak; ``inclusion_drop_from_peak`` flags features
    whose latest window is materially below their best stretch.

sign_flip_rate
    Fraction of consecutive non-zero Lasso coefficient pairs where the sign
    inverts. High flip rate ⇒ unstable predictor (likely multicollinearity
    or an unstable shrinkage solution).

importance_slope / importance_slope_pvalue
    OLS slope of ``mean_importance ~ step_idx`` for XGB. Negative slope with
    p<0.10 ⇒ measurable decay in that horizon.

decay_score
    Convenience ranking metric in [0, 1]: weighted blend of inclusion drop,
    sign flip rate, and (when negative) importance slope. Higher = more
    decayed. Use this only for triage; consult the underlying components
    before retiring a feature.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..config import load_config
from ..utils import DECIMAL_PRECISION, round_for_output


ROLLING_WINDOW = 8        # steps (~32 trading weeks at 20-BDay cadence)
INCLUSION_DROP_THRESHOLD = 0.30   # flag when latest is ≥30% below peak


# ---------------------------------------------------------------------------
# Lasso-side metrics
# ---------------------------------------------------------------------------

def _lasso_metrics(detailed: pd.DataFrame) -> pd.DataFrame:
    """
    Compute (horizon × feature) decay metrics from per-step Lasso records.

    Aggregates folds within each (horizon, step, feature) by averaging coefs,
    then computes rolling inclusion frequency and sign-flip rate over the
    step axis.
    """
    if detailed.empty:
        return pd.DataFrame()

    # Average across folds within (step, horizon, feature)
    by_step = (
        detailed.groupby(["horizon", "feature", "step"], as_index=False)["coef"]
        .mean()
        .sort_values(["horizon", "feature", "step"])
    )

    rows: list = []
    for (horizon, feature), grp in by_step.groupby(["horizon", "feature"]):
        coefs = grp["coef"].to_numpy()
        n = len(coefs)
        if n == 0:
            continue

        nonzero_mask = coefs != 0

        # Rolling inclusion frequency
        if n >= ROLLING_WINDOW:
            rolling_incl = (
                pd.Series(nonzero_mask.astype(float))
                .rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW)
                .mean()
                .dropna()
                .to_numpy()
            )
            latest_incl = float(rolling_incl[-1]) if len(rolling_incl) else float("nan")
            peak_incl = float(rolling_incl.max()) if len(rolling_incl) else float("nan")
        else:
            latest_incl = float(nonzero_mask.mean())
            peak_incl = latest_incl

        drop_from_peak = (peak_incl - latest_incl) if peak_incl > 0 else 0.0
        decayed_flag = bool(drop_from_peak >= INCLUSION_DROP_THRESHOLD)

        # Sign flips over consecutive non-zero coefs
        nz = coefs[nonzero_mask]
        if len(nz) >= 2:
            signs = np.sign(nz)
            flips = int(np.sum(signs[1:] != signs[:-1]))
            flip_rate = flips / (len(nz) - 1)
        else:
            flips = 0
            flip_rate = 0.0

        rows.append({
            "horizon": int(horizon),
            "feature": feature,
            "n_steps": n,
            "rolling_inclusion_freq": latest_incl,
            "peak_inclusion_freq": peak_incl,
            "inclusion_drop_from_peak": drop_from_peak,
            "decayed_inclusion_flag": decayed_flag,
            "sign_flips": flips,
            "sign_flip_rate": flip_rate,
            "mean_abs_coef": float(np.abs(coefs).mean()),
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# XGB-side metrics
# ---------------------------------------------------------------------------

def _xgb_metrics(steps: pd.DataFrame) -> pd.DataFrame:
    """
    Linear-trend test on per-step XGB importances.

    For each (horizon, feature), fit ``importance ~ step`` via OLS and report
    the slope and a two-sided t-test p-value. Negative slope + small p ⇒
    importance is trending down over time.
    """
    if steps.empty:
        return pd.DataFrame()

    rows: list = []
    for (horizon, feature), grp in steps.groupby(["horizon", "feature"]):
        x = grp["step"].to_numpy(dtype=float)
        y = grp["importance"].to_numpy(dtype=float)
        n = len(x)
        if n < 4 or np.std(x) == 0 or np.std(y) == 0:
            rows.append({
                "horizon": int(horizon),
                "feature": feature,
                "importance_slope": float("nan"),
                "importance_slope_pvalue": float("nan"),
                "mean_importance": float(y.mean()) if n else 0.0,
            })
            continue

        # OLS via closed form
        x_mean = x.mean()
        y_mean = y.mean()
        sxx = float(np.sum((x - x_mean) ** 2))
        sxy = float(np.sum((x - x_mean) * (y - y_mean)))
        slope = sxy / sxx
        intercept = y_mean - slope * x_mean
        resid = y - (intercept + slope * x)
        dof = n - 2
        if dof <= 0 or sxx <= 0:
            pvalue = float("nan")
        else:
            sigma2 = float(np.sum(resid ** 2)) / dof
            se_slope = np.sqrt(sigma2 / sxx) if sigma2 >= 0 else float("nan")
            if not np.isfinite(se_slope) or se_slope <= 0:
                pvalue = float("nan")
            else:
                t_stat = slope / se_slope
                # Two-sided t-test via scipy if available, else Normal approx.
                try:
                    from scipy.stats import t as _t
                    pvalue = float(2 * (1 - _t.cdf(abs(t_stat), df=dof)))
                except Exception:
                    from math import erf, sqrt
                    pvalue = float(2 * (1 - 0.5 * (1 + erf(abs(t_stat) / sqrt(2)))))

        rows.append({
            "horizon": int(horizon),
            "feature": feature,
            "importance_slope": slope,
            "importance_slope_pvalue": pvalue,
            "mean_importance": float(y.mean()),
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Combined per-ticker computation
# ---------------------------------------------------------------------------

def compute_feature_decay(
    ticker: str,
    results_dir: Path,
) -> Optional[pd.DataFrame]:
    """
    Read lasso/xgb step CSVs for *ticker* and emit feature_decay_{ticker}.csv.

    Returns the resulting DataFrame, or None if neither input is present.
    """
    lasso_path = results_dir / f"lasso_detailed_{ticker}.csv"
    xgb_path = results_dir / f"xgb_importance_steps_{ticker}.csv"

    has_lasso = lasso_path.exists()
    has_xgb = xgb_path.exists()
    if not (has_lasso or has_xgb):
        print(f"[FEATURE_DECAY] {ticker}: no input CSVs found "
              f"(expected {lasso_path.name} and/or {xgb_path.name})")
        return None

    lasso_metrics = _lasso_metrics(pd.read_csv(lasso_path)) if has_lasso else pd.DataFrame()
    xgb_metrics = _xgb_metrics(pd.read_csv(xgb_path)) if has_xgb else pd.DataFrame()

    if lasso_metrics.empty and xgb_metrics.empty:
        print(f"[FEATURE_DECAY] {ticker}: empty input — skipping")
        return None

    if lasso_metrics.empty:
        merged = xgb_metrics
    elif xgb_metrics.empty:
        merged = lasso_metrics
    else:
        merged = lasso_metrics.merge(
            xgb_metrics, on=["horizon", "feature"], how="outer",
        )

    merged.insert(0, "ticker", ticker)
    merged["decay_score"] = _decay_score(merged)
    merged.sort_values(["horizon", "decay_score"], ascending=[True, False], inplace=True)

    merged = round_for_output(merged, DECIMAL_PRECISION)

    out_path = results_dir / f"feature_decay_{ticker}.csv"
    merged.to_csv(out_path, index=False)
    print(f"[FEATURE_DECAY] {ticker}: wrote {out_path.name} "
          f"({len(merged)} feature×horizon rows)")
    return merged


def _decay_score(df: pd.DataFrame) -> pd.Series:
    """
    Heuristic [0, 1] decay score for triage ranking.

    Components (each clipped to [0, 1]):
        inclusion_drop_from_peak  — how far below peak the rolling inclusion sits
        sign_flip_rate            — fraction of sign reversals in non-zero coefs
        max(0, -slope_norm)       — only penalise negative XGB slope; normalise
                                    by feature's mean importance to compare across
                                    features with different importance scales

    Weights are equal across the three components when all are present.
    """
    incl = df.get("inclusion_drop_from_peak", pd.Series(0.0, index=df.index)).fillna(0.0).clip(0, 1)
    flip = df.get("sign_flip_rate", pd.Series(0.0, index=df.index)).fillna(0.0).clip(0, 1)
    slope = df.get("importance_slope", pd.Series(np.nan, index=df.index))
    mean_imp = df.get("mean_importance", pd.Series(np.nan, index=df.index))
    slope_norm = pd.Series(0.0, index=df.index)
    valid = slope.notna() & mean_imp.notna() & (mean_imp.abs() > 1e-9)
    slope_norm[valid] = (-slope[valid] / mean_imp[valid].abs()).clip(0, 1)
    return ((incl + flip + slope_norm) / 3.0).astype(float)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Per-feature decay analysis from backtest tracking CSVs.",
    )
    parser.add_argument(
        "--ticker", default=None,
        help="Single ticker to analyse (e.g., AAPL).",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Run for every configured ticker and emit a corpus summary.",
    )
    parser.add_argument(
        "--results-dir", default=None,
        help="Override results directory (default: BacktestConfig.results_dir).",
    )
    args = parser.parse_args()

    if not args.ticker and not args.all:
        parser.error("must pass --ticker TICKER or --all")

    _, _, bc = load_config()
    results_dir = Path(args.results_dir) if args.results_dir else bc.results_dir

    if args.ticker:
        compute_feature_decay(args.ticker.upper(), results_dir)
        return

    # --all mode: scan results_dir for known input files and aggregate.
    dc, _, _ = load_config()
    per_ticker: List[pd.DataFrame] = []
    for ticker in dc.tickers:
        df = compute_feature_decay(ticker, results_dir)
        if df is not None:
            per_ticker.append(df)

    if not per_ticker:
        print("[FEATURE_DECAY] No tickers produced output — nothing to summarise.")
        return

    combined = pd.concat(per_ticker, ignore_index=True)
    summary = (
        combined.groupby(["horizon", "feature"], as_index=False)
        .agg(
            n_tickers=("ticker", "nunique"),
            mean_inclusion_drop=("inclusion_drop_from_peak", "mean"),
            mean_sign_flip_rate=("sign_flip_rate", "mean"),
            mean_importance_slope=("importance_slope", "mean"),
            mean_decay_score=("decay_score", "mean"),
        )
        .sort_values(["horizon", "mean_decay_score"], ascending=[True, False])
    )
    summary = round_for_output(summary, DECIMAL_PRECISION)
    out_path = results_dir / "feature_decay_summary.csv"
    summary.to_csv(out_path, index=False)
    print(f"[FEATURE_DECAY] Corpus summary -> {out_path}")


if __name__ == "__main__":
    main()

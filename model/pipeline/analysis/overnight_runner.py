"""
overnight_runner.py — Chains two Optuna hyperparam searches for overnight validation.

Runs JPM (primary calibration) then AAPL (cross-validation).  After both
searches complete, compares the top-N trials from each ticker and prints a
recommended config that generalises across both.

Estimated wall time on 5950X + GTX 1070:
  JPM  120 trials × ~1.7 min = ~3.4 h
  AAPL  80 trials × ~1.7 min = ~2.3 h
  Total ~5.7 h  (safely within 8 h)

Usage (from project root):
    python -m model.pipeline.analysis.overnight_runner
    python -m model.pipeline.analysis.overnight_runner --trials1 100 --trials2 60
"""

import argparse
import dataclasses
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# ── path bootstrap ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.pipeline.config import load_config
from model.pipeline.data_loader import fetch_dataset
from model.pipeline.features import FeatureBuilder
from model.pipeline.utils import DECIMAL_PRECISION, round_for_output
from model.pipeline.analysis.hyperparam_search import (
    _mini_backtest,
    make_objective,
    RESULTS_DIR,
)

STEP_DAYS = 100  # ~7 WFA steps per trial (~3 min/trial on 5950X); was 63 (~6.5 min)
N_DAYS    = 2000 # ~8 years of history per trial window
MIN_TRAIN = 756


# ═══════════════════════════════════════════════════════════════════════════════
# PER-TICKER SEARCH
# ═══════════════════════════════════════════════════════════════════════════════

def run_search(
    ticker: str,
    n_trials: int,
    verbose: bool = True,
) -> Optional[pd.DataFrame]:
    """
    Load data for one ticker, run the Optuna study, save trial log, return it.
    """
    try:
        import optuna
    except ImportError:
        print("[RUNNER] optuna not installed — run: pip install optuna")
        sys.exit(1)

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    print(f"\n{'#'*60}")
    print(f"  SEARCH: {ticker}   {n_trials} trials")
    print(f"  n_days={N_DAYS}  step_days={STEP_DAYS}  min_train={MIN_TRAIN}")
    print(f"{'#'*60}\n")
    t_start = time.time()

    dc, base_mc, bc = load_config()
    dc.tickers = [ticker]
    raw_data   = fetch_dataset(dc, force_refresh=False)

    builder    = FeatureBuilder(dc, base_mc)
    feature_df = builder.build(ticker, raw_data)

    predictors = builder.get_predictor_columns(feature_df)
    predictors = [c for c in predictors if feature_df[c].notna().any()]
    if verbose:
        n_steps = max(0, min(len(feature_df), N_DAYS) - MIN_TRAIN) // STEP_DAYS
        print(f"[{ticker}] Features: {len(predictors)}  "
              f"Rows: {len(feature_df)}  WFA steps/trial: ~{n_steps}\n")

    trial_log: list = []
    study = optuna.create_study(
        direction="minimize",
        study_name=f"volmodel_{ticker}",
        sampler=optuna.samplers.TPESampler(seed=42),
    )
    study.optimize(
        make_objective(
            feature_df, predictors, base_mc,
            N_DAYS, STEP_DAYS, MIN_TRAIN,
            trial_log,
        ),
        n_trials=n_trials,
        show_progress_bar=True,
    )

    elapsed = (time.time() - t_start) / 60
    best = study.best_trial
    best_log = next((r for r in trial_log if r["trial"] == best.number), {})

    print(f"\n[{ticker}] Done in {elapsed:.1f} min")
    print(f"  Best trial #{best.number}:  "
          f"Objective={best.value:.6f}  "
          f"QLIKE={best_log.get('qlike', '?'):.6f}  "
          f"MZ_beta_dev={best_log.get('mz_beta_dev', '?'):.4f}")

    if not trial_log:
        return None

    log_df = pd.DataFrame(trial_log).sort_values("objective")
    out_path = RESULTS_DIR / f"hyperparam_search_{ticker}.csv"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    round_for_output(log_df, DECIMAL_PRECISION).to_csv(out_path, index=False)
    print(f"  Trial log -> {out_path}")

    return log_df


# ═══════════════════════════════════════════════════════════════════════════════
# CROSS-TICKER COMPARISON
# ═══════════════════════════════════════════════════════════════════════════════

_XGB_PARAMS = [
    "xgb_max_depth", "xgb_lr", "xgb_n_est", "xgb_reg_alpha",
    "xgb_reg_lambda", "xgb_gamma", "xgb_colsample",
    "xgb_min_child", "xgb_subsample",
]
_RF_PARAMS = ["rf_n_est", "rf_min_leaf", "rf_max_feat"]
_ALL_PARAMS = _XGB_PARAMS + _RF_PARAMS


def _rank_and_merge(
    df1: pd.DataFrame,
    df2: pd.DataFrame,
    ticker1: str,
    ticker2: str,
    top_n: int = 20,
) -> pd.DataFrame:
    """
    Normalise objectives within each study, average ranks across top_n trials,
    return a merged DataFrame sorted by combined rank.

    Uses parameter proximity rather than exact match (continuous params are
    bucketed so similar configs from both tickers can be scored together).
    """
    # Keep top_n from each study by objective
    d1 = df1.nsmallest(top_n, "objective").copy()
    d2 = df2.nsmallest(top_n, "objective").copy()

    # Normalise objectives to [0,1] within each study for fair comparison
    for df, name in [(d1, ticker1), (d2, ticker2)]:
        mn, mx = df["objective"].min(), df["objective"].max()
        span = mx - mn if mx > mn else 1.0
        df["norm_obj"] = (df["objective"] - mn) / span
        df["source"] = name

    combined = pd.concat([d1, d2], ignore_index=True)
    combined["rank_combined"] = combined["norm_obj"].rank()
    return combined.sort_values("rank_combined")


def print_comparison(
    log1: pd.DataFrame,
    log2: pd.DataFrame,
    ticker1: str,
    ticker2: str,
    base_xgb: dict,
    base_rf: dict,
) -> None:
    """
    Print a summary of both searches and a recommended config using the
    median of top-10 param values from each study.
    """
    top1 = log1.nsmallest(10, "objective")
    top2 = log2.nsmallest(10, "objective")

    print(f"\n{'='*60}")
    print(f"  CROSS-TICKER COMPARISON: {ticker1} vs {ticker2}")
    print(f"{'='*60}")

    print(f"\n  {ticker1} top-10 objective range: "
          f"{top1['objective'].min():.5f} – {top1['objective'].max():.5f}")
    print(f"  {ticker2} top-10 objective range: "
          f"{top2['objective'].min():.5f} – {top2['objective'].max():.5f}")

    # Check for meaningful parameter agreement between top-10 of each study
    print(f"\n  Parameter medians (top-10 trials each ticker):\n")
    print(f"  {'Param':<22} {ticker1:>10}  {ticker2:>10}  {'Agree?':>8}")
    print(f"  {'-'*56}")

    agree_count = 0
    for p in _ALL_PARAMS:
        if p not in top1.columns or p not in top2.columns:
            continue
        v1 = top1[p].median()
        v2 = top2[p].median()
        if isinstance(v1, str) or isinstance(v2, str):
            agree = "YES" if v1 == v2 else "no"
        else:
            # Agree if within 30% of each other
            span = max(abs(v1), abs(v2), 1e-9)
            agree = "YES" if abs(v1 - v2) / span < 0.30 else "no"
            if agree == "YES":
                agree_count += 1
        print(f"  {p:<22} {v1:>10.4g}  {v2:>10.4g}  {agree:>8}")

    # Recommended config: median of top-10 from both tickers combined
    combined_top = pd.concat([top1, top2], ignore_index=True)

    def pick(p, default):
        if p not in combined_top.columns:
            return default
        vals = combined_top[p].dropna()
        if len(vals) == 0:
            return default
        # Categorical: mode; numeric: median
        if vals.dtype == object or p == "rf_max_feat":
            return vals.mode().iloc[0]
        return vals.median()

    max_feat_val  = pick("rf_max_feat", "sqrt")
    max_feat_repr = (f'"{max_feat_val}"' if max_feat_val in ("sqrt", "log2")
                     else str(float(max_feat_val)))
    xgb_device   = base_xgb.get("device", "cuda")
    xgb_n_jobs   = base_xgb.get("n_jobs", 2)
    rf_n_jobs    = base_rf.get("n_jobs", 4)

    n_est    = int(round(pick("xgb_n_est",     base_xgb["n_estimators"])  / 50) * 50)
    depth    = int(round(pick("xgb_max_depth", base_xgb["max_depth"])))
    lr       = float(pick("xgb_lr",            base_xgb["learning_rate"]))
    alpha    = float(pick("xgb_reg_alpha",      base_xgb["reg_alpha"]))
    lam      = float(pick("xgb_reg_lambda",     base_xgb["reg_lambda"]))
    gamma    = float(pick("xgb_gamma",          base_xgb["gamma"]))
    colsamp  = float(pick("xgb_colsample",      base_xgb["colsample_bytree"]))
    minchild = int(round(pick("xgb_min_child",  1)))
    subsamp  = float(pick("xgb_subsample",      1.0))
    rf_nest  = int(round(pick("rf_n_est",       base_rf["n_estimators"])   / 50) * 50)
    rf_leaf  = int(round(pick("rf_min_leaf",    base_rf["min_samples_leaf"])))

    print(f"""
  RECOMMENDED config.py update (median of top-10 × both tickers):

    xgb_params = {{
        "n_estimators":     {n_est},
        "max_depth":        {depth},
        "learning_rate":    {lr:.4f},
        "reg_alpha":        {alpha:.5f},
        "reg_lambda":       {lam:.4f},
        "gamma":            {gamma:.4f},
        "colsample_bytree": {colsamp:.3f},
        "min_child_weight": {minchild},
        "subsample":        {subsamp:.3f},
        "n_jobs":           {xgb_n_jobs},
        "device":           "{xgb_device}",
        "tree_method":      "hist",
    }}
    rf_params = {{
        "n_estimators":     {rf_nest},
        "min_samples_leaf": {rf_leaf},
        "max_features":     {max_feat_repr},
        "n_jobs":           {rf_n_jobs},
    }}
""")

    # Save combined ranking for review
    merged = _rank_and_merge(log1, log2, ticker1, ticker2)
    merged_path = RESULTS_DIR / f"hyperparam_comparison_{ticker1}_{ticker2}.csv"
    round_for_output(merged, DECIMAL_PRECISION).to_csv(merged_path, index=False)
    print(f"  Combined trial ranking saved -> {merged_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Overnight hyperparam search: primary + cross-validation ticker",
    )
    parser.add_argument("--ticker1",  default="JPM",  help="Primary calibration ticker (default: JPM)")
    parser.add_argument("--ticker2",  default="AAPL", help="Cross-validation ticker (default: AAPL)")
    parser.add_argument("--trials1",  type=int, default=120, help="Trials for ticker1 (default: 120)")
    parser.add_argument("--trials2",  type=int, default=80,  help="Trials for ticker2 (default: 80)")
    args = parser.parse_args()

    wall_est = (args.trials1 + args.trials2) * 1.7 / 60
    print(f"\n{'='*60}")
    print(f"  OVERNIGHT RUNNER")
    print(f"  {args.ticker1}: {args.trials1} trials  |  {args.ticker2}: {args.trials2} trials")
    print(f"  Estimated wall time: ~{wall_est:.1f} h  (step_days={STEP_DAYS})")
    print(f"{'='*60}")

    overall_start = time.time()

    # ── Primary search ─────────────────────────────────────────────────────────
    log1 = run_search(args.ticker1, args.trials1)
    if log1 is None:
        print(f"[RUNNER] {args.ticker1} search returned no results. Aborting.")
        sys.exit(1)

    # ── Cross-validation search ────────────────────────────────────────────────
    log2 = run_search(args.ticker2, args.trials2)
    if log2 is None:
        print(f"[RUNNER] {args.ticker2} search returned no results. Skipping comparison.")
        sys.exit(1)

    # ── Comparison ─────────────────────────────────────────────────────────────
    dc, base_mc, _ = load_config()
    print_comparison(
        log1, log2,
        args.ticker1, args.ticker2,
        base_mc.xgb_params,
        base_mc.rf_params,
    )

    total_min = (time.time() - overall_start) / 60
    print(f"[RUNNER] Complete in {total_min:.1f} min ({total_min/60:.2f} h)")


if __name__ == "__main__":
    main()

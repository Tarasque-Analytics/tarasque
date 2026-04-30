"""
hyperparam_search.py — Optuna hyperparameter search for EnsembleVolModel.

Objective: minimize  QLIKE + 0.3 * |MZ_beta - 1.0|^2  across all horizons
on a mini walk-forward (last n_days of data, larger step_days for speed).

Data and features are loaded ONCE before the study.  Each trial only re-runs
the cheap walk-forward loop with a fresh ModelConfig.

Usage (from project root):
    python -m model.pipeline.analysis.hyperparam_search
    python -m model.pipeline.analysis.hyperparam_search --ticker JPM --trials 100
    python -m model.pipeline.analysis.hyperparam_search --ticker AAPL --trials 50 --n-days 1500

Output:
    model/pipeline/results/hyperparam_search_{TICKER}.csv — full trial log
    Best params printed as a copy-paste-ready config.py block.

Requirements: pip install optuna
"""

import argparse
import contextlib
import copy
import dataclasses
import io
import sys
import warnings
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from ..utils import DECIMAL_PRECISION, round_for_output

warnings.filterwarnings("ignore")

# ── path bootstrap ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.pipeline.config import load_config, ModelConfig
from model.pipeline.data_loader import fetch_dataset
from model.pipeline.features import FeatureBuilder
from model.pipeline.models import EnsembleVolModel

RESULTS_DIR = Path("model/pipeline/results")

# MZ_beta calibration penalty weight.
# Set low (0.02) so QLIKE dominates the objective — MZ_beta is a structural
# property of the training window and barely moves with hyperparameters, so a
# high penalty (e.g. 0.30) causes it to dominate the ranking while providing
# almost no signal about which params are actually better.
# 0.02 means a 0.20-unit beta deviation adds only 0.0008 to the objective —
# detectable but not overwhelming relative to typical QLIKE differences (~0.003).
MZ_BETA_PENALTY = 0.02


# ═══════════════════════════════════════════════════════════════════════════════
# MINI WALK-FORWARD
# ═══════════════════════════════════════════════════════════════════════════════

def _mini_backtest(
    feature_df: pd.DataFrame,
    predictors: List[str],
    mc: ModelConfig,
    n_days: int,
    step_days: int,
    min_train: int,
) -> Dict[str, float]:
    """
    Single-ticker mini walk-forward backtest for one Optuna trial.

    Returns {"qlike": ..., "mz_beta_dev": ..., "objective": ...}.
    Higher trial noise is acceptable; Optuna's TPE averages over many trials.
    """
    # Trim to last n_days for speed
    if len(feature_df) > n_days:
        feature_df = feature_df.iloc[-n_days:]

    all_qlike: List[float] = []
    all_mz_beta_dev: List[float] = []

    for h in mc.horizons:
        target_col = f"y_{h}"
        if target_col not in feature_df.columns:
            continue

        all_dates = feature_df.index[min_train:]
        test_starts = all_dates[::step_days]
        preds_rows: list = []

        for t_date in test_starts:
            t_pos = feature_df.index.get_loc(t_date)
            train = feature_df.iloc[:t_pos]
            test  = feature_df.iloc[t_pos : t_pos + step_days]

            if len(test) == 0 or len(train) < min_train:
                continue

            X_tr = train[predictors]
            y_tr_dict = {
                hh: train[f"y_{hh}"]
                for hh in mc.horizons
                if f"y_{hh}" in train.columns
            }
            X_te = test[predictors]

            train_medians = X_tr.median()
            X_tr = X_tr.ffill().bfill().fillna(train_medians).fillna(0)
            X_te = X_te.ffill().bfill().fillna(train_medians).fillna(0)

            try:
                model = EnsembleVolModel(mc)
                # Suppress per-fold print noise from model training
                with contextlib.redirect_stdout(io.StringIO()):
                    model.train_wfa(X_tr, y_tr_dict, splits=3)
                pred_curves = model.predict_curve_batch(X_te)

                for i, idx in enumerate(X_te.index):
                    yt_log = feature_df.loc[idx, target_col]
                    if pd.isna(yt_log):
                        continue
                    preds_rows.append({
                        "y_true": float(np.exp(yt_log)),
                        "y_pred": float(pred_curves[h][i]),
                    })
            except Exception:
                continue

        if len(preds_rows) < 30:
            continue

        pred_df = pd.DataFrame(preds_rows)
        y_true  = np.clip(pred_df["y_true"].values, 1e-6, None)
        y_pred  = np.clip(pred_df["y_pred"].values, 1e-6, None)

        # QLIKE
        ratio = y_true / y_pred
        all_qlike.append(float(np.mean(ratio - np.log(ratio) - 1)))

        # MZ beta deviation from 1.0
        lr = LinearRegression()
        lr.fit(y_pred.reshape(-1, 1), y_true)
        all_mz_beta_dev.append(abs(float(lr.coef_[0]) - 1.0))

    if not all_qlike:
        return {"qlike": 999.0, "mz_beta_dev": 999.0, "objective": 999.0}

    mean_qlike     = float(np.mean(all_qlike))
    mean_mz_dev    = float(np.mean(all_mz_beta_dev))
    objective      = mean_qlike + MZ_BETA_PENALTY * mean_mz_dev ** 2

    return {"qlike": mean_qlike, "mz_beta_dev": mean_mz_dev, "objective": objective}


# ═══════════════════════════════════════════════════════════════════════════════
# OPTUNA OBJECTIVE
# ═══════════════════════════════════════════════════════════════════════════════

def make_objective(
    feature_df: pd.DataFrame,
    predictors: List[str],
    base_mc: ModelConfig,
    n_days: int,
    step_days: int,
    min_train: int,
    trial_log: list,
):
    """
    Factory that returns an Optuna-compatible objective function.

    trial_log is mutated in-place so the caller can inspect all trials even
    if the study is interrupted early.
    """
    def objective(trial):
        # ── XGBoost search space ────────────────────────────────────────────
        new_xgb = dict(base_mc.xgb_params)  # copy to avoid mutating base
        new_xgb["max_depth"]         = trial.suggest_int  ("xgb_max_depth",  2, 6)
        new_xgb["learning_rate"]     = trial.suggest_float("xgb_lr",         0.01, 0.20, log=True)
        new_xgb["n_estimators"]      = trial.suggest_int  ("xgb_n_est",      50,  300, step=50)
        new_xgb["reg_alpha"]         = trial.suggest_float("xgb_reg_alpha",  1e-3, 2.0, log=True)
        new_xgb["reg_lambda"]        = trial.suggest_float("xgb_reg_lambda", 0.1,  5.0, log=True)
        new_xgb["gamma"]             = trial.suggest_float("xgb_gamma",      0.0,  0.5)
        new_xgb["colsample_bytree"]  = trial.suggest_float("xgb_colsample",  0.5,  1.0)
        new_xgb["min_child_weight"]  = trial.suggest_int  ("xgb_min_child",  1, 10)
        new_xgb["subsample"]         = trial.suggest_float("xgb_subsample",  0.6,  1.0)

        # ── Random Forest search space ──────────────────────────────────────
        new_rf = dict(base_mc.rf_params)
        new_rf["n_estimators"]     = trial.suggest_int("rf_n_est",   50, 200, step=50)
        new_rf["min_samples_leaf"] = trial.suggest_int("rf_min_leaf", 2,  15)
        # max_features: sklearn accepts "sqrt", "log2", or a float fraction
        mf_str = trial.suggest_categorical("rf_max_feat", ["sqrt", "log2", "0.3", "0.5"])
        new_rf["max_features"] = float(mf_str) if mf_str not in ("sqrt", "log2") else mf_str

        # Disable quantile model during search — it's not part of the objective
        # and its overhead would inflate trial time by ~15%.
        mc = dataclasses.replace(
            base_mc,
            xgb_params=new_xgb,
            rf_params=new_rf,
            quantile_alphas=[],
        )

        scores = _mini_backtest(
            feature_df, predictors, mc,
            n_days, step_days, min_train,
        )

        trial_log.append({
            "trial":       trial.number,
            "objective":   scores["objective"],
            "qlike":       scores["qlike"],
            "mz_beta_dev": scores["mz_beta_dev"],
            **trial.params,
        })

        return scores["objective"]

    return objective


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Optuna hyperparameter search for EnsembleVolModel",
    )
    parser.add_argument("--ticker",    default="JPM",  help="Calibration ticker (default: JPM)")
    parser.add_argument("--trials",    type=int, default=100,  help="Optuna trials (default: 100)")
    parser.add_argument("--n-days",    type=int, default=2000, help="History window in days (default: 2000, ~8yr)")
    parser.add_argument("--step-days", type=int, default=50,   help="WFA step size for search (default: 50)")
    parser.add_argument("--min-train", type=int, default=756,  help="Min training rows (default: 756)")
    args = parser.parse_args()

    print(f"[SEARCH] Ticker={args.ticker}  Trials={args.trials}  "
          f"n_days={args.n_days}  step_days={args.step_days}")

    # ── Load data and build features ONCE ─────────────────────────────────────
    print(f"\n[SEARCH] Loading data for {args.ticker}...")
    dc, base_mc, bc = load_config()
    dc.tickers = [args.ticker]
    raw_data = fetch_dataset(dc, force_refresh=False)

    builder    = FeatureBuilder(dc, base_mc)
    feature_df = builder.build(args.ticker, raw_data)

    predictors = builder.get_predictor_columns(feature_df)
    predictors = [c for c in predictors if feature_df[c].notna().any()]
    print(f"[SEARCH] Features: {len(predictors)}  Total rows: {len(feature_df)}")

    trimmed_len = min(len(feature_df), args.n_days)
    n_steps     = max(0, trimmed_len - args.min_train) // args.step_days
    print(f"[SEARCH] Mini-backtest: ~{n_steps} WFA steps × {len(base_mc.horizons)} horizons per trial")
    print(f"[SEARCH] Estimated trial time: ~{n_steps * 4 // 60 + 1}–{n_steps * 8 // 60 + 1} min per 10 trials\n")

    # ── Run Optuna study ───────────────────────────────────────────────────────
    try:
        import optuna
    except ImportError:
        print("[SEARCH] optuna not installed. Run: pip install optuna")
        sys.exit(1)

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    trial_log: list = []
    study = optuna.create_study(
        direction="minimize",
        study_name=f"volmodel_{args.ticker}",
        sampler=optuna.samplers.TPESampler(seed=42),
    )
    study.optimize(
        make_objective(
            feature_df, predictors, base_mc,
            args.n_days, args.step_days, args.min_train,
            trial_log,
        ),
        n_trials=args.trials,
        show_progress_bar=True,
    )

    # ── Results ────────────────────────────────────────────────────────────────
    best     = study.best_trial
    best_log = next((r for r in trial_log if r["trial"] == best.number), {})

    print(f"\n{'='*60}")
    print(f"  BEST TRIAL: #{best.number}   Objective = {best.value:.6f}")
    print(f"  QLIKE = {best_log.get('qlike', '?'):.6f}   "
          f"MZ_beta_dev = {best_log.get('mz_beta_dev', '?'):.4f}")
    print(f"{'='*60}")

    bp = best.params
    print("\n  XGBoost params:")
    for k in sorted(k for k in bp if k.startswith("xgb_")):
        print(f"    {k}: {bp[k]}")
    print("\n  RF params:")
    for k in sorted(k for k in bp if k.startswith("rf_")):
        print(f"    {k}: {bp[k]}")

    # Save trial log
    if trial_log:
        log_df = pd.DataFrame(trial_log).sort_values("objective")
        out_path = RESULTS_DIR / f"hyperparam_search_{args.ticker}.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        round_for_output(log_df, DECIMAL_PRECISION).to_csv(out_path, index=False)
        print(f"\n[SEARCH] Trial log saved -> {out_path}")
        print("\n  Top 5 trials:")
        print(log_df[["trial", "objective", "qlike", "mz_beta_dev"]].head(5).to_string(index=False))

    # Print copy-pasteable config block
    max_feat_val = bp.get("rf_max_feat", "sqrt")
    max_feat_repr = (
        f'"{max_feat_val}"' if max_feat_val in ("sqrt", "log2")
        else str(float(max_feat_val))
    )
    xgb_device  = base_mc.xgb_params.get("device", "cuda")
    xgb_n_jobs  = base_mc.xgb_params.get("n_jobs", 2)
    rf_n_jobs   = base_mc.rf_params.get("n_jobs", 4)
    print(f"""
[SEARCH] Suggested config.py update for ModelConfig:

    xgb_params = {{
        "n_estimators":     {bp.get("xgb_n_est",      base_mc.xgb_params["n_estimators"])},
        "max_depth":        {bp.get("xgb_max_depth",  base_mc.xgb_params["max_depth"])},
        "learning_rate":    {bp.get("xgb_lr",         base_mc.xgb_params["learning_rate"]):.4f},
        "reg_alpha":        {bp.get("xgb_reg_alpha",  base_mc.xgb_params["reg_alpha"]):.5f},
        "reg_lambda":       {bp.get("xgb_reg_lambda", base_mc.xgb_params["reg_lambda"]):.4f},
        "gamma":            {bp.get("xgb_gamma",      base_mc.xgb_params["gamma"]):.4f},
        "colsample_bytree": {bp.get("xgb_colsample",  base_mc.xgb_params["colsample_bytree"]):.3f},
        "min_child_weight": {bp.get("xgb_min_child",  1)},
        "subsample":        {bp.get("xgb_subsample",  1.0):.3f},
        "n_jobs":           {xgb_n_jobs},
        "device":           "{xgb_device}",
        "tree_method":      "hist",
    }}
    rf_params = {{
        "n_estimators":     {bp.get("rf_n_est",    base_mc.rf_params["n_estimators"])},
        "min_samples_leaf": {bp.get("rf_min_leaf", base_mc.rf_params["min_samples_leaf"])},
        "max_features":     {max_feat_repr},
        "n_jobs":           {rf_n_jobs},
    }}
""")


if __name__ == "__main__":
    main()

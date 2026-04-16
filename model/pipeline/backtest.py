"""
backtest.py — Walk-forward backtesting engine.

Metrics:
    RMSE              — standard forecast error
    Mincer-Zarnowitz  — regress actual on predicted (summary_march16.md:24,76)
    QLIKE             — asymmetric quasi-likelihood loss (summary_march16.md:26)
    Event capture     — % of 2σ events where model spiked first (summary_march16.md:27)
"""
import os
import time as _time
import numpy as np
import pandas as pd
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from sklearn.linear_model import LinearRegression
from .models import EnsembleVolModel as _EnsembleVolModel

from .config import DataConfig, ModelConfig, BacktestConfig
from .features import FeatureBuilder
from .models import EnsembleVolModel


# ═══════════════════════════════════════════════════════════════════════════
# TOP-LEVEL WORKER (must be picklable for ProcessPoolExecutor)
# ═══════════════════════════════════════════════════════════════════════════

def _backtest_one_ticker(
    ticker: str,
    raw_data: Dict[str, pd.DataFrame],
    dc: DataConfig,
    mc: ModelConfig,
    bc: BacktestConfig,
    model_names: Optional[List[str]],
) -> Tuple[str, List[dict], Optional[str]]:
    """
    Run backtest for a single ticker in a worker process.

    Returns (ticker, metrics_rows, error_msg).
    error_msg is None on success.
    """
    try:
        engine = BacktestEngine(dc, mc, bc)
        builder = FeatureBuilder(dc, mc)
        feature_df = builder.build(ticker, raw_data)
        results = engine.run_single_ticker(ticker, feature_df, model_names=model_names)

        rows = []
        for r in results:
            row = {"ticker": ticker, "horizon": r.horizon}
            row.update(r.metrics)
            rows.append(row)
        return (ticker, rows, None)
    except Exception as e:
        return (ticker, [], str(e))


# ═══════════════════════════════════════════════════════════════════════════
# RESULT CONTAINER
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BacktestResult:
    ticker: str
    horizon: int
    predictions: pd.DataFrame   # columns: date, y_true, y_pred
    metrics: Dict[str, float]


# ═══════════════════════════════════════════════════════════════════════════
# ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class BacktestEngine:

    def __init__(
        self,
        data_config: DataConfig,
        model_config: ModelConfig,
        backtest_config: BacktestConfig,
    ):
        self.dc = data_config
        self.mc = model_config
        self.bc = backtest_config

    # ── Single ticker ─────────────────────────────────────────────────

    def run_single_ticker(
        self,
        ticker: str,
        feature_df: pd.DataFrame,
        model_names: Optional[List[str]] = None,
    ) -> List[BacktestResult]:
        """
        Walk-forward backtest for one ticker across all horizons.

        At each step:
          1. Train on expanding (or rolling) window up to t
          2. Predict the next step_days rows
          3. Collect OOS predictions
          4. Advance by step_days and repeat
        """
        builder = FeatureBuilder(self.dc, self.mc)
        predictors = builder.get_predictor_columns(feature_df)
        step = self.bc.step_days

        # Drop features that are entirely NaN across the full window
        # (e.g. FRED macro features when WRDS subscription is unavailable).
        valid_predictors = [c for c in predictors if feature_df[c].notna().any()]
        dropped = set(predictors) - set(valid_predictors)
        if dropped:
            print(f"[BACKTEST] Dropping {len(dropped)} all-NaN feature(s): "
                  f"{sorted(dropped)}")
        predictors = valid_predictors

        results: List[BacktestResult] = []
        # Lasso tracking: accumulate fold-level records across all steps.
        # Only collect on first horizon pass — train_wfa() trains all horizons
        # internally, so subsequent outer-loop passes would triple-count.
        ticker_lasso_records: list[dict] = []
        # XGB importance: {horizon: np.ndarray summed across steps}
        xgb_imp_sum: Dict[int, np.ndarray] = {}
        xgb_imp_count: Dict[int, int] = {}
        _first_h = self.mc.horizons[0] if self.mc.horizons else None

        for h in self.mc.horizons:
            target_col = f"y_{h}"
            if target_col not in feature_df.columns:
                continue

            # Minimum training rows: max(252, 20 * n_features)
            min_train = max(252, 20 * len(predictors))
            all_dates = feature_df.index[min_train:]
            test_starts = all_dates[::step]

            all_preds: list[dict] = []
            weights_history: list[dict] = []  # Track ensemble weights per WF step

            print(f"[BACKTEST] {ticker} H={h}: {len(test_starts)} walk-forward steps "
                  f"({len(predictors)} features, min_train={min_train})")

            for t_idx, t_date in enumerate(test_starts):
                # Determine training window
                t_pos = feature_df.index.get_loc(t_date)
                if self.bc.window_type == "rolling":
                    train_start = max(0, t_pos - self.bc.rolling_window_days)
                else:
                    train_start = 0
                train_end = t_pos

                train = feature_df.iloc[train_start:train_end]
                test = feature_df.iloc[train_end:train_end + step]

                if len(test) == 0 or len(train) < min_train:
                    continue

                X_tr = train[predictors]
                # Pass all horizon targets — train_wfa trains all horizons in one pass.
                y_tr_dict = {
                    hh: train[f"y_{hh}"]
                    for hh in self.mc.horizons
                    if f"y_{hh}" in train.columns
                }
                X_te = test[predictors]

                # Impute remaining NaN (rolling burn-in, sparse IV gaps).
                # ffill within window, bfill for leading NaN, then median fallback.
                # Final fillna(0): catches columns that are entirely NaN within this
                # window (e.g. zscore needs 252d burn-in; early folds have no valid
                # median to fill from).
                train_medians = X_tr.median()
                X_tr = X_tr.ffill().bfill().fillna(train_medians).fillna(0)
                X_te = X_te.ffill().bfill().fillna(train_medians).fillna(0)

                # Train a fresh model for this window
                model = EnsembleVolModel(self.mc)
                model.train_wfa(X_tr, y_tr_dict, splits=3, model_names=model_names)

                # Capture Lasso records on first horizon pass only
                if h == _first_h and model.lasso_log:
                    for rec in model.lasso_log:
                        ticker_lasso_records.append({**rec, "step": t_idx})

                # Accumulate XGB feature importances across steps (all horizons)
                for hh in self.mc.horizons:
                    xgb_model = model.models[hh].get("XGB")
                    if xgb_model is not None and hasattr(xgb_model, "feature_importances_"):
                        imp = xgb_model.feature_importances_
                        if hh not in xgb_imp_sum:
                            xgb_imp_sum[hh] = np.zeros(len(imp))
                            xgb_imp_count[hh] = 0
                        xgb_imp_sum[hh] += imp
                        xgb_imp_count[hh] += 1

                # Batch-predict all test rows at once
                try:
                    pred_curves, per_model_curves = model.predict_curve_batch_detailed(X_te)
                    for i, idx in enumerate(X_te.index):
                        row = {
                            "date": idx,
                            "y_true": float(np.exp(feature_df.loc[idx, target_col])),
                            "y_pred": float(pred_curves[h][i]),
                        }
                        # Per-model predictions
                        for mname in per_model_curves.get(h, {}):
                            row[f"pred_{mname}"] = float(per_model_curves[h][mname][i])
                        all_preds.append(row)

                    # Track weights for this WF step
                    weights_history.append({
                        "step": t_idx,
                        "date": str(t_date)[:10],
                        **{f"w_{k}": v for k, v in model.weights[h].items()},
                        **{f"cv_rmse_{k}": v for k, v in model.cv_rmse.get(h, {}).items()},
                    })
                except Exception:
                    pass

                # Progress
                if (t_idx + 1) % 10 == 0:
                    print(f"  Step {t_idx + 1}/{len(test_starts)}")

            if not all_preds:
                print(f"[BACKTEST] {ticker} H={h}: No predictions generated.")
                continue

            pred_df = pd.DataFrame(all_preds)

            # Also pull in the vrp_wedge value at each prediction date
            # so the analysis scripts have it without rebuilding features.
            if "vrp_wedge" in feature_df.columns:
                pred_df = pred_df.merge(
                    feature_df[["vrp_wedge"]].rename_axis("date").reset_index(),
                    on="date", how="left",
                )
            if "put_call_skew_30d" in feature_df.columns:
                pred_df = pred_df.merge(
                    feature_df[["put_call_skew_30d"]].rename_axis("date").reset_index(),
                    on="date", how="left",
                )

            # Save per-ticker/horizon predictions for analysis scripts
            self.bc.results_dir.mkdir(parents=True, exist_ok=True)
            pred_path = self.bc.results_dir / f"predictions_{ticker}_H{h}.csv"
            pred_df.to_csv(pred_path, index=False)

            # Save weights history for this ticker/horizon
            if weights_history:
                wh_df = pd.DataFrame(weights_history)
                wh_path = self.bc.results_dir / f"weights_history_{ticker}_H{h}.csv"
                wh_df.to_csv(wh_path, index=False)

            metrics = self._compute_metrics(pred_df, feature_df, h)

            # Store actual ensemble weights in metrics for JSON output
            if weights_history:
                last_w = weights_history[-1]
                for key in ["w_XGB", "w_RF", "w_LassoCV"]:
                    if key in last_w:
                        metrics[key] = last_w[key]

            print(f"  [RESULT] RMSE={metrics['rmse']:.4f} | "
                  f"MZ_beta={metrics['mz_beta']:.3f} | "
                  f"MZ_R2={metrics['mz_r2']:.3f} | "
                  f"QLIKE={metrics['qlike']:.4f}")

            results.append(BacktestResult(
                ticker=ticker, horizon=h,
                predictions=pred_df, metrics=metrics,
            ))

        # Write Lasso tracking summary
        if ticker_lasso_records:
            self._write_lasso_summary(ticker, predictors, ticker_lasso_records)

        # Write XGB importance summary
        if xgb_imp_sum:
            self._write_xgb_importance(ticker, predictors, xgb_imp_sum, xgb_imp_count)

        # Print model timing breakdown for this ticker
        prof = _EnsembleVolModel._profile
        if prof:
            total = sum(prof.values())
            parts = "  |  ".join(f"{k}: {v:.1f}s ({100*v/total:.0f}%)" for k,v in sorted(prof.items()))
            print(f"  [PROFILE] {ticker} model fit time — {parts}  |  total: {total:.1f}s")
            _EnsembleVolModel._profile.clear()

        return results

    # ── Lasso summary ─────────────────────────────────────────────────

    def _write_lasso_summary(
        self,
        ticker: str,
        feature_names: List[str],
        records: list,
    ) -> None:
        """
        Aggregate per-fold Lasso records into a per-feature summary CSV.

        Columns: ticker, horizon, feature, inclusion_freq, mean_abs_coef,
                 mean_lambda, n_fits
        """
        rows = []
        for rec in records:
            for i, fname in enumerate(feature_names):
                rows.append({
                    "ticker": ticker,
                    "horizon": rec["horizon"],
                    "stage": rec["stage"],
                    "step": rec["step"],
                    "fold": rec["fold"],
                    "alpha": rec["alpha"],
                    "feature": fname,
                    "coef": rec["coefs"][i] if i < len(rec["coefs"]) else 0.0,
                })
        if not rows:
            return
        import pandas as _pd
        df = _pd.DataFrame(rows)
        summary = (
            df.groupby(["feature", "horizon"])
            .agg(
                inclusion_freq=("coef", lambda x: (x != 0).mean()),
                mean_abs_coef=("coef", lambda x: x.abs().mean()),
                mean_lambda=("alpha", "mean"),
                n_fits=("coef", "count"),
            )
            .reset_index()
        )
        summary.insert(0, "ticker", ticker)
        summary.sort_values(["horizon", "inclusion_freq"], ascending=[True, False], inplace=True)
        self.bc.results_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.bc.results_dir / f"lasso_tracking_{ticker}.csv"
        summary.to_csv(out_path, index=False)
        print(f"  [LASSO] Tracking saved -> {out_path.name}")

    def _write_xgb_importance(
        self,
        ticker: str,
        feature_names: List[str],
        imp_sum: Dict[int, np.ndarray],
        imp_count: Dict[int, int],
    ) -> None:
        """Write mean XGB feature importances (averaged across WFA steps) to CSV."""
        import pandas as _pd
        rows = []
        for h, total in imp_sum.items():
            mean_imp = total / max(imp_count[h], 1)
            for i, fname in enumerate(feature_names):
                rows.append({
                    "ticker": ticker,
                    "horizon": h,
                    "feature": fname,
                    "mean_importance": float(mean_imp[i]) if i < len(mean_imp) else 0.0,
                })
        if not rows:
            return
        df = _pd.DataFrame(rows)
        df.sort_values(["horizon", "mean_importance"], ascending=[True, False], inplace=True)
        self.bc.results_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.bc.results_dir / f"xgb_importance_{ticker}.csv"
        df.to_csv(out_path, index=False)
        print(f"  [XGB] Importance saved -> {out_path.name}")

    # ── Sector sweep ──────────────────────────────────────────────────

    def run_sector_sweep(
        self,
        raw_data: Dict[str, pd.DataFrame],
        model_names: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Run backtest across all configured tickers. Returns combined metrics."""
        import time
        all_metrics: list[dict] = []

        n_total = len(self.dc.tickers)
        sweep_start = time.time()
        n_workers = self.bc.parallel_tickers

        if n_workers > 1 and n_total > 1:
            all_metrics = self._run_parallel(raw_data, model_names, n_workers)
        else:
            all_metrics = self._run_sequential(raw_data, model_names)

        if all_metrics:
            summary = pd.DataFrame(all_metrics)
            self.bc.results_dir.mkdir(parents=True, exist_ok=True)

            # ── Aggregate metrics ─────────────────────────────────────
            out_path = self.bc.results_dir / "backtest_results.csv"
            summary.to_csv(out_path, index=False)
            print(f"\n[BACKTEST] Results saved to {out_path}")

            # ── Per-prediction data ───────────────────────────────────
            # Needed by vrp_analysis.py and residual_analysis.py.
            all_pred_frames = []
            for ticker in self.dc.tickers:
                for h in self.mc.horizons:
                    pred_path = (
                        self.bc.results_dir / f"predictions_{ticker}_H{h}.csv"
                    )
                    if pred_path.exists():
                        df = pd.read_csv(pred_path)
                        df["ticker"] = ticker
                        df["horizon"] = h
                        all_pred_frames.append(df)
            if all_pred_frames:
                combined_preds = pd.concat(all_pred_frames, ignore_index=True)
                combined_path = self.bc.results_dir / "all_predictions.csv"
                combined_preds.to_csv(combined_path, index=False)
                print(f"[BACKTEST] Combined predictions saved to {combined_path}")

            # ── Generate standardized JSON output ─────────────────────
            self._generate_json_output(raw_data, all_metrics)

            return summary

        return pd.DataFrame()

    # ── Sequential / Parallel execution ─────────────────────────────

    def _run_sequential(
        self,
        raw_data: Dict[str, pd.DataFrame],
        model_names: Optional[List[str]],
    ) -> list[dict]:
        """Original sequential ticker loop."""
        import time
        builder = FeatureBuilder(self.dc, self.mc)
        all_metrics: list[dict] = []
        n_total = len(self.dc.tickers)
        sweep_start = time.time()

        for ticker_idx, ticker in enumerate(self.dc.tickers):
            elapsed = time.time() - sweep_start
            pct = ticker_idx / n_total * 100
            eta_str = ""
            if ticker_idx > 0:
                eta_sec = elapsed / ticker_idx * (n_total - ticker_idx)
                eta_str = f"  ETA ~{eta_sec/60:.0f}m"
            print(f"\n{'='*50}")
            print(f"  BACKTEST: {ticker}  [{ticker_idx+1}/{n_total}  {pct:.0f}%{eta_str}]")
            print(f"{'='*50}")

            try:
                feature_df = builder.build(ticker, raw_data)
            except Exception as e:
                print(f"[ERROR] Feature build failed for {ticker}: {e}")
                continue

            results = self.run_single_ticker(
                ticker, feature_df, model_names=model_names,
            )

            for r in results:
                row = {"ticker": ticker, "horizon": r.horizon}
                row.update(r.metrics)
                all_metrics.append(row)

        return all_metrics

    def _run_parallel(
        self,
        raw_data: Dict[str, pd.DataFrame],
        model_names: Optional[List[str]],
        n_workers: int,
    ) -> list[dict]:
        """Parallel ticker processing via ProcessPoolExecutor."""
        import time
        all_metrics: list[dict] = []
        n_total = len(self.dc.tickers)
        completed = 0
        sweep_start = time.time()

        # Cap workers to cpu_count / 4 — each worker runs RF/LassoCV with n_jobs=4,
        # so total CPU threads = n_workers × 4 ≤ cpu_count. XGB uses CUDA independently.
        max_safe = max(1, (os.cpu_count() or 4) // 4)
        n_workers = min(n_workers, n_total, max_safe)

        print(f"\n[BACKTEST] Parallel sweep: {n_total} tickers, {n_workers} workers")

        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            futures = {
                executor.submit(
                    _backtest_one_ticker,
                    ticker, raw_data,
                    self.dc, self.mc, self.bc, model_names,
                ): ticker
                for ticker in self.dc.tickers
            }

            for future in as_completed(futures):
                ticker = futures[future]
                completed += 1
                elapsed = time.time() - sweep_start

                try:
                    ticker_name, rows, error_msg = future.result()
                except Exception as e:
                    print(f"\n[ERROR] {ticker} worker crashed: {e}")
                    continue

                if error_msg:
                    print(f"\n[ERROR] {ticker} failed: {error_msg}")
                    continue

                eta_str = ""
                if completed > 0 and completed < n_total:
                    eta_sec = elapsed / completed * (n_total - completed)
                    eta_str = f"  ETA ~{eta_sec/60:.0f}m"

                print(f"\n{'='*50}")
                print(f"  DONE: {ticker_name}  [{completed}/{n_total}{eta_str}]")
                for r in rows:
                    print(f"    H={r['horizon']}: RMSE={r['rmse']:.4f} | "
                          f"MZ_beta={r['mz_beta']:.3f} | R2={r['mz_r2']:.3f}")
                print(f"{'='*50}")

                all_metrics.extend(rows)

        return all_metrics

    # ── JSON output generation ─────────────────────────────────────

    def _generate_json_output(
        self,
        raw_data: Dict[str, pd.DataFrame],
        all_metrics: list[dict],
    ):
        """
        Generate standardized JSON output for frontend consumption.

        Reads back per-ticker prediction CSVs and feature data to produce:
          - {TICKER}_Payload.json for each ticker
          - market_overview.json for the macro landing page
          - metrics_summary.json for internal monitoring
        """
        from .output import write_ticker_payload, write_market_overview, write_metrics_summary

        payload_dir = self.bc.results_dir / "payloads"
        builder = FeatureBuilder(self.dc, self.mc)

        # Build sector map from compustat_meta if available
        sector_map: Dict[str, str] = {}
        if "compustat_meta" in raw_data and raw_data["compustat_meta"] is not None:
            meta_df = raw_data["compustat_meta"]
            if "tic" in meta_df.columns and "gsector" in meta_df.columns:
                for _, row in meta_df.iterrows():
                    sector_map[row["tic"]] = str(row["gsector"])

        # Collect per-ticker data for payloads
        ticker_payloads: Dict[str, dict] = {}
        all_predictions: Dict[str, Dict[int, pd.DataFrame]] = {}

        # Build metrics lookup: {(ticker, horizon): metrics_dict}
        metrics_by_th = {}
        for m in all_metrics:
            key = (m["ticker"], m["horizon"])
            metrics_by_th[key] = m

        for ticker in self.dc.tickers:
            # Load predictions from saved CSVs
            predictions: Dict[int, pd.DataFrame] = {}
            ticker_metrics: Dict[int, Dict[str, float]] = {}
            for h in self.mc.horizons:
                pred_path = self.bc.results_dir / f"predictions_{ticker}_H{h}.csv"
                if pred_path.exists():
                    predictions[h] = pd.read_csv(pred_path)
                if (ticker, h) in metrics_by_th:
                    ticker_metrics[h] = metrics_by_th[(ticker, h)]

            if not predictions:
                continue

            all_predictions[ticker] = predictions

            # Build feature_df for this ticker to extract latest values
            try:
                feature_df = builder.build(ticker, raw_data)
            except Exception as e:
                print(f"[OUTPUT] Skipping {ticker} payload — feature build failed: {e}")
                continue

            # Extract actual ensemble weights from metrics (stored during WF run)
            weights: Dict[int, Dict[str, float]] = {}
            for h in predictions.keys():
                m = metrics_by_th.get((ticker, h), {})
                weights[h] = {
                    "XGB": m.get("w_XGB", 0.33),
                    "RF": m.get("w_RF", 0.33),
                    "LassoCV": m.get("w_LassoCV", 0.33),
                }

            write_ticker_payload(
                ticker=ticker,
                predictions=predictions,
                feature_df=feature_df,
                metrics=ticker_metrics,
                weights=weights,
                sector_code=sector_map.get(ticker),
                output_dir=payload_dir,
            )

            # Read back the payload for market overview aggregation
            payload_path = payload_dir / f"{ticker}_Payload.json"
            if payload_path.exists():
                import json
                with open(payload_path) as f:
                    ticker_payloads[ticker] = json.load(f)

        # Write market overview
        if ticker_payloads:
            write_market_overview(
                ticker_payloads=ticker_payloads,
                all_predictions=all_predictions,
                sector_map=sector_map,
                output_dir=payload_dir,
            )

        # Write metrics summary
        write_metrics_summary(all_metrics, payload_dir)

        print(f"\n[OUTPUT] All JSON payloads written to {payload_dir}")

    # ── Metrics ───────────────────────────────────────────────────────

    def _compute_metrics(
        self,
        pred_df: pd.DataFrame,
        feature_df: pd.DataFrame,
        horizon: int,
    ) -> Dict[str, float]:
        metrics: Dict[str, float] = {}

        y_true = pred_df["y_true"].values
        y_pred = pred_df["y_pred"].values

        # Clip to avoid numerical issues
        y_true = np.clip(y_true, 1e-6, None)
        y_pred = np.clip(y_pred, 1e-6, None)

        # 1. RMSE
        metrics["rmse"] = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))

        # 2. Mincer-Zarnowitz regression: y_true = α + β * y_pred + ε
        #    Ideal: α ≈ 0, β ≈ 1, R² high
        lr = LinearRegression()
        lr.fit(y_pred.reshape(-1, 1), y_true)
        metrics["mz_alpha"] = float(lr.intercept_)
        metrics["mz_beta"] = float(lr.coef_[0])
        metrics["mz_r2"] = float(lr.score(y_pred.reshape(-1, 1), y_true))

        # 3. QLIKE (quasi-likelihood loss)
        #    QLIKE = mean(y_true/y_pred - log(y_true/y_pred) - 1)
        ratio = y_true / y_pred
        metrics["qlike"] = float(np.mean(ratio - np.log(ratio) - 1))

        # 4. Event capture rate
        #    What fraction of ≥2σ realised vol spikes did the model
        #    predict elevated vol for?
        metrics["event_capture_rate"] = self._event_capture_rate(
            pred_df, feature_df, horizon,
        )

        # 5. Pinball (quantile) loss at τ = 0.10, 0.50, 0.90
        for tau in [0.10, 0.50, 0.90]:
            diff = y_true - y_pred
            metrics[f"pinball_{int(tau*100)}"] = float(
                np.mean(np.maximum(tau * diff, (tau - 1) * diff))
            )

        metrics["n_predictions"] = len(y_true)

        return metrics

    def _event_capture_rate(
        self,
        pred_df: pd.DataFrame,
        feature_df: pd.DataFrame,
        horizon: int,
    ) -> Optional[float]:
        """
        % of ≥2σ actual vol events where model predicted above-average vol.
        """
        if len(pred_df) < 50:
            return None

        y_true = pred_df["y_true"].values
        y_pred = pred_df["y_pred"].values

        mean_true = np.mean(y_true)
        std_true = np.std(y_true)

        if std_true < 1e-6:
            return None

        # Events: actual vol ≥ mean + 2σ
        event_mask = y_true >= (mean_true + 2 * std_true)
        n_events = event_mask.sum()

        if n_events == 0:
            return None

        # Model "captured" the event if its prediction was above average
        captured = (y_pred[event_mask] > mean_true).sum()
        return float(captured / n_events)

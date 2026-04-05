"""
backtest.py — Walk-forward backtesting engine.

Metrics:
    RMSE              — standard forecast error
    Mincer-Zarnowitz  — regress actual on predicted (summary_march16.md:24,76)
    QLIKE             — asymmetric quasi-likelihood loss (summary_march16.md:26)
    Event capture     — % of 2σ events where model spiked first (summary_march16.md:27)
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from sklearn.linear_model import LinearRegression

from .config import DataConfig, ModelConfig, BacktestConfig
from .features import FeatureBuilder
from .models import EnsembleVolModel


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

        for h in self.mc.horizons:
            target_col = f"y_{h}"
            if target_col not in feature_df.columns:
                continue

            # Minimum training rows: max(252, 20 * n_features)
            min_train = max(252, 20 * len(predictors))
            all_dates = feature_df.index[min_train:]
            test_starts = all_dates[::step]

            all_preds: list[dict] = []

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

                # Predict each test row
                for idx in X_te.index:
                    row = X_te.loc[[idx]]
                    try:
                        pred_curve = model.predict_curve(row)
                        all_preds.append({
                            "date": idx,
                            "y_true": float(np.exp(feature_df.loc[idx, target_col])),
                            "y_pred": pred_curve[h],
                        })
                    except Exception:
                        continue

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

            metrics = self._compute_metrics(pred_df, feature_df, h)

            print(f"  [RESULT] RMSE={metrics['rmse']:.4f} | "
                  f"MZ_beta={metrics['mz_beta']:.3f} | "
                  f"MZ_R2={metrics['mz_r2']:.3f} | "
                  f"QLIKE={metrics['qlike']:.4f}")

            results.append(BacktestResult(
                ticker=ticker, horizon=h,
                predictions=pred_df, metrics=metrics,
            ))

        return results

    # ── Sector sweep ──────────────────────────────────────────────────

    def run_sector_sweep(
        self,
        raw_data: Dict[str, pd.DataFrame],
        model_names: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Run backtest across all configured tickers. Returns combined metrics."""
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

            return summary

        return pd.DataFrame()

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

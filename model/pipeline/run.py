"""
run.py — CLI orchestrator for the Tarasque model pipeline.

Usage:
    python -m model.pipeline.run --mode backtest --base-dir /path/to/data
    python -m model.pipeline.run --mode backtest --tickers AAPL MSFT --base-dir D:/Tarasque_DB
    python -m model.pipeline.run --mode refresh_data --base-dir /path/to/data
    python -m model.pipeline.run --mode live --tickers AAPL
    python -m model.pipeline.run --mode forecast --retrain --tickers AAPL
    python -m model.pipeline.run --mode forecast --tickers AAPL          # daily refresh
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

from .config import load_config
from .data_loader import fetch_dataset, append_recent_data
from .features import FeatureBuilder
from .models import EnsembleVolModel, GarchForecaster
from .backtest import BacktestEngine
from .utils import DECIMAL_PRECISION, round_for_output


def run_full_pipeline(
    base_dir: str = None,
    mode: str = "backtest",
    tickers: list = None,
    model_names: list = None,
    force_refresh: bool = False,
    retrain: bool = False,
):
    """
    Main entry point.

    Parameters
    ----------
    mode : str
        "refresh_data" — query WRDS / append Alpaca, save Parquet
        "backtest"     — full walk-forward evaluation across tickers
        "live"         — single-day inference for given tickers (always retrains)
        "forecast"     — production forward forecast; loads persisted model
                          unless ``retrain`` is set, in which case it trains
                          and serializes a new model for the cycle.
    model_names : list[str], optional
        Subset of ["XGB", "RF", "LassoCV"] for ablation.
    force_refresh : bool
        Re-download even if Parquet cache exists.
    retrain : bool
        Forecast mode only — force a fresh `train_wfa` and overwrite the
        persisted model. Use this at every cycle start (every 20 BDays).
    """
    dc, mc, bc = load_config(base_dir)

    if tickers:
        dc.tickers = tickers

    # ── Step 1: Data ──────────────────────────────────────────────────
    print("\n[PIPELINE] Fetching dataset...")
    raw_data = fetch_dataset(dc, force_refresh=force_refresh)

    if mode == "refresh_data":
        print("[PIPELINE] Appending recent data from Alpaca/yfinance...")
        raw_data = append_recent_data(dc, raw_data)
        print("[PIPELINE] Data refresh complete.")
        _print_data_summary(raw_data)
        return

    # ── Step 2: Backtest ──────────────────────────────────────────────
    if mode == "backtest":
        engine = BacktestEngine(dc, mc, bc)
        results = engine.run_sector_sweep(raw_data, model_names=model_names)

        if not results.empty:
            print("\n" + "=" * 60)
            print("  BACKTEST SUMMARY")
            print("=" * 60)
            print(results.to_string(index=False))
        return results

    # ── Step 3: Live inference ────────────────────────────────────────
    if mode == "live":
        builder = FeatureBuilder(dc, mc)

        for ticker in dc.tickers:
            print(f"\n{'='*50}")
            print(f"  LIVE ANALYSIS: {ticker}")
            print(f"{'='*50}")

            try:
                feature_df = builder.build(ticker, raw_data)
            except Exception as e:
                print(f"[ERROR] Feature build failed: {e}")
                continue

            predictors = builder.get_predictor_columns(feature_df)
            X = feature_df[predictors]
            y_dict = {h: feature_df[f"y_{h}"] for h in mc.horizons}

            # Train ensemble
            model = EnsembleVolModel(mc)
            model.train_wfa(X, y_dict, model_names=model_names)

            # GARCH overlay
            returns = feature_df["ret_TARGET"].dropna()
            garch_vol, _ = GarchForecaster.fit_predict(
                returns, horizon=21, dist=mc.garch_dist,
            )

            # Forecast
            current_features = X.iloc[[-1]]
            rv_curve = model.predict_curve(current_features)
            fair_atm_vol = 0.25 * garch_vol + 0.75 * rv_curve[21]

            print(f"  GARCH (21d):    {garch_vol:.2%}")
            print(f"  ML Ensemble:    {rv_curve[21]:.2%} / {rv_curve[63]:.2%} / {rv_curve[126]:.2%}")
            print(f"  Fair ATM Vol:   {fair_atm_vol:.2%}")
            print(f"  Blended RMSE:   {model.rmse_scores[21]:.4f}")
            print(f"  Top drivers:    {model.feature_importance}")

        return

    # ── Step 4: Production forward forecast ──────────────────────────
    if mode == "forecast":
        return _run_forecast(
            dc, mc, bc, raw_data, model_names=model_names, retrain=retrain,
        )


def _run_forecast(
    dc, mc, bc, raw_data: dict,
    model_names: list = None,
    retrain: bool = False,
):
    """
    Forward-forecast cycle.

    With ``retrain=True``: refit on the full history through today's data and
    persist the model under ``results/forecasts/{TICKER}_model_{cycle}.joblib``.
    Without it: load the most recent persisted model and run inference only.
    The output CSV ``forecast_{run_date}.csv`` is the same shape in both cases.
    """
    raw_data = append_recent_data(dc, raw_data)
    builder = FeatureBuilder(dc, mc)
    forecast_dir = bc.results_dir / "forecasts"
    forecast_dir.mkdir(parents=True, exist_ok=True)

    today = pd.Timestamp.today().normalize()
    run_date = today.date().isoformat()
    window_end = (today + pd.tseries.offsets.BDay(20)).date().isoformat()

    rows: list = []
    for ticker in dc.tickers:
        print(f"\n{'='*50}")
        print(f"  FORECAST: {ticker}  (retrain={retrain})")
        print(f"{'='*50}")

        try:
            feature_df = builder.build(ticker, raw_data)
        except Exception as e:
            print(f"[ERROR] Feature build failed for {ticker}: {e}")
            continue

        predictors = builder.get_predictor_columns(feature_df)
        valid_predictors = [c for c in predictors if feature_df[c].notna().any()]
        X = feature_df[valid_predictors]
        y_dict = {
            h: feature_df[f"y_{h}"]
            for h in mc.horizons
            if f"y_{h}" in feature_df.columns
        }

        # Impute predictor NaN the same way backtest does, so live features
        # match training-time conditioning.
        X = X.ffill().bfill().fillna(X.median()).fillna(0)

        # Find the most recent persisted model for this ticker.
        existing = sorted(forecast_dir.glob(f"{ticker}_model_*.joblib"))
        target_path = forecast_dir / f"{ticker}_model_{run_date}.joblib"

        if retrain or not existing:
            print(f"[FORECAST] Training new model for {ticker}...")
            model = EnsembleVolModel(mc)
            model.train_wfa(X, y_dict, model_names=model_names)
            model.save(target_path)
            print(f"[FORECAST] Saved model -> {target_path.name}")
        else:
            load_path = existing[-1]
            print(f"[FORECAST] Loading persisted model {load_path.name}")
            model = EnsembleVolModel.load(load_path)
            # Align feature columns to the trained model's predictor set.
            missing = [c for c in model.predictors if c not in X.columns]
            if missing:
                print(f"[FORECAST] WARNING — {len(missing)} predictors absent from"
                      f" current features; filling with 0: {missing[:5]}...")
                for c in missing:
                    X[c] = 0.0
            X = X[model.predictors]

        latest = X.iloc[[-1]]
        try:
            curve = model.predict_curve(latest)
        except Exception as e:
            print(f"[ERROR] predict_curve failed for {ticker}: {e}")
            continue

        rows.append({
            "ticker": ticker,
            "cycle_start_date": run_date,
            "window_end_date": window_end,
            "forecast_h21":  float(curve.get(21, float("nan"))),
            "forecast_h63":  float(curve.get(63, float("nan"))),
            "forecast_h126": float(curve.get(126, float("nan"))),
        })

        print(f"  H21={curve.get(21, float('nan')):.4f} | "
              f"H63={curve.get(63, float('nan')):.4f} | "
              f"H126={curve.get(126, float('nan')):.4f}")

    if not rows:
        print("[FORECAST] No forecasts generated.")
        return

    out_df = pd.DataFrame(rows)
    out_df = round_for_output(out_df, DECIMAL_PRECISION)
    out_path = forecast_dir / f"forecast_{run_date}.csv"
    out_df.to_csv(out_path, index=False)
    print(f"\n[FORECAST] Wrote {out_path} ({len(out_df)} tickers)")
    return out_df


def _print_data_summary(raw_data: dict):
    """Print row counts for each data type."""
    print("\n[DATA SUMMARY]")
    for key, df in raw_data.items():
        if isinstance(df, pd.DataFrame):
            print(f"  {key:20s}: {len(df):>8,} rows")
        else:
            print(f"  {key:20s}: (not a DataFrame)")


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Tarasque Model Pipeline — volatility forecasting framework",
    )
    parser.add_argument(
        "--mode", default="backtest",
        choices=["backtest", "refresh_data", "live", "forecast"],
        help="Pipeline mode (default: backtest)",
    )
    parser.add_argument(
        "--base-dir", default=None,
        help="Parquet storage root (overrides TARASQUE_BASE_DIR env var)",
    )
    parser.add_argument(
        "--tickers", nargs="+", default=None,
        help="Override ticker list (e.g., --tickers AAPL MSFT)",
    )
    parser.add_argument(
        "--models", nargs="+", default=None,
        choices=["XGB", "RF", "LassoCV"],
        help="Subset of models for ablation (default: all three)",
    )
    parser.add_argument(
        "--force-refresh", action="store_true",
        help="Re-download data even if Parquet cache exists",
    )
    parser.add_argument(
        "--retrain", action="store_true",
        help="Forecast mode only: refit on full history and persist the model "
             "(use at every 20-BDay cycle start; omit for daily refreshes)",
    )

    args = parser.parse_args()

    run_full_pipeline(
        base_dir=args.base_dir,
        mode=args.mode,
        tickers=args.tickers,
        model_names=args.models,
        force_refresh=args.force_refresh,
        retrain=args.retrain,
    )


if __name__ == "__main__":
    main()

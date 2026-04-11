"""
run.py — CLI orchestrator for the Tarasque model pipeline.

Usage:
    python -m model.pipeline.run --mode backtest --base-dir /path/to/data
    python -m model.pipeline.run --mode backtest --tickers AAPL MSFT --base-dir D:/Tarasque_DB
    python -m model.pipeline.run --mode refresh_data --base-dir /path/to/data
    python -m model.pipeline.run --mode live --tickers AAPL
"""
import argparse
import sys
from pathlib import Path

from .config import load_config
from .data_loader import fetch_dataset, append_recent_data
from .features import FeatureBuilder
from .models import EnsembleVolModel, GarchForecaster
from .backtest import BacktestEngine


def run_full_pipeline(
    base_dir: str = None,
    mode: str = "backtest",
    tickers: list = None,
    model_names: list = None,
    force_refresh: bool = False,
):
    """
    Main entry point.

    Parameters
    ----------
    mode : str
        "refresh_data" — query WRDS / append Alpaca, save Parquet
        "backtest"     — full walk-forward evaluation across tickers
        "live"         — single-day inference for given tickers
    model_names : list[str], optional
        Subset of ["XGB", "RF", "LassoCV"] for ablation.
    force_refresh : bool
        Re-download even if Parquet cache exists.
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


def _print_data_summary(raw_data: dict):
    """Print row counts for each data type."""
    print("\n[DATA SUMMARY]")
    for key, df in raw_data.items():
        if isinstance(df, pd.DataFrame):
            print(f"  {key:20s}: {len(df):>8,} rows")
        else:
            print(f"  {key:20s}: (not a DataFrame)")


# Need pandas for _print_data_summary
import pandas as pd


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Tarasque Model Pipeline — volatility forecasting framework",
    )
    parser.add_argument(
        "--mode", default="backtest",
        choices=["backtest", "refresh_data", "live"],
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

    args = parser.parse_args()

    run_full_pipeline(
        base_dir=args.base_dir,
        mode=args.mode,
        tickers=args.tickers,
        model_names=args.models,
        force_refresh=args.force_refresh,
    )


if __name__ == "__main__":
    main()

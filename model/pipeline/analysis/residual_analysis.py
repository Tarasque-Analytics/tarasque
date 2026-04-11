"""
residual_analysis.py — Standalone residual diagnostic tool.

Purpose
-------
After a backtest run, identify *systematic* factors that drive prediction
error.  Findings feed back into features.py as new event/regime features
(in the same way FOMC dates and earnings were added).

What this script tests
----------------------
  1. Worst-residual dates   — which specific dates/tickers drive the
                              largest errors, and are they clustered?
  2. Cross-ticker co-movement — do large residuals co-occur across tickers
                              on the same calendar date (systematic shock
                              not captured by the model)?
  3. Macro-regime clustering  — are large residuals concentrated in specific
                              VIX regimes, drawdown periods, or macro events
                              (e.g. Fed meeting windows)?
  4. Autocorrelation          — are residuals serially correlated? (implies
                              a missing regime/trend feature)
  5. Sector clustering        — do residuals cluster by GICS sector?
  6. Horizon comparison        — does residual structure change with horizon?

Usage
-----
    python -m model.pipeline.analysis.residual_analysis
    python -m model.pipeline.analysis.residual_analysis --horizon 21
    python -m model.pipeline.analysis.residual_analysis --top-n 20 --threshold 2.0
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_predictions(results_dir: Path) -> pd.DataFrame:
    combined = results_dir / "all_predictions.csv"
    if combined.exists():
        df = pd.read_csv(combined, parse_dates=["date"])
        print(f"[RESID] Loaded {len(df):,} predictions from {combined.name}")
        return df

    frames = []
    for f in sorted(results_dir.glob("predictions_*_H*.csv")):
        parts = f.stem.split("_")
        ticker = parts[1]
        horizon = int(parts[2][1:])
        df = pd.read_csv(f, parse_dates=["date"])
        df["ticker"] = ticker
        df["horizon"] = horizon
        frames.append(df)

    if not frames:
        print(f"[RESID] No prediction files found in {results_dir}")
        sys.exit(1)

    return pd.concat(frames, ignore_index=True)


def _sigma_threshold_mask(series: pd.Series, sigma: float = 2.0) -> pd.Series:
    """Return boolean mask for |x| > sigma * std(x)."""
    thr = sigma * series.std()
    return series.abs() > thr


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------

def _worst_dates(df: pd.DataFrame, horizon: int, top_n: int = 20) -> pd.DataFrame:
    """Return the top_n dates with the largest mean |residual| across tickers."""
    sub = df[df["horizon"] == horizon].copy()
    sub["abs_resid"] = (sub["y_true"] - sub["y_pred"]).abs()
    by_date = (
        sub.groupby("date")
        .agg(
            mean_abs_resid=("abs_resid", "mean"),
            max_abs_resid=("abs_resid", "max"),
            n_tickers=("ticker", "nunique"),
            tickers=("ticker", lambda x: ", ".join(sorted(x.unique()))),
        )
        .reset_index()
        .sort_values("mean_abs_resid", ascending=False)
        .head(top_n)
    )
    return by_date


def _cross_ticker_clustering(df: pd.DataFrame, horizon: int, sigma: float = 2.0) -> pd.DataFrame:
    """
    On which dates do ≥3 tickers simultaneously have large residuals?
    These are systematic shocks the model missed universally.
    """
    sub = df[df["horizon"] == horizon].copy()
    sub["signed_resid"] = sub["y_true"] - sub["y_pred"]
    sub["large"] = _sigma_threshold_mask(sub["signed_resid"], sigma)

    clustered = (
        sub[sub["large"]]
        .groupby("date")
        .agg(
            n_large=("ticker", "nunique"),
            tickers=("ticker", lambda x: ", ".join(sorted(x.unique()))),
            mean_resid=("signed_resid", "mean"),
            direction=("signed_resid", lambda x: "under" if x.mean() < 0 else "over"),
        )
        .reset_index()
        .query("n_large >= 3")
        .sort_values("n_large", ascending=False)
    )
    return clustered


def _autocorrelation(df: pd.DataFrame, horizon: int, max_lag: int = 10) -> pd.DataFrame:
    """
    Mean Ljung-Box ACF for residuals per ticker.  High ACF → missing regime.
    Returns per-lag mean ACF and Ljung-Box p-value.
    """
    rows = []
    sub = df[df["horizon"] == horizon].copy()
    sub["signed_resid"] = sub["y_true"] - sub["y_pred"]

    for ticker in sub["ticker"].unique():
        ts = sub[sub["ticker"] == ticker].sort_values("date")["signed_resid"].dropna()
        if len(ts) < 30:
            continue
        for lag in range(1, max_lag + 1):
            acf_val = ts.autocorr(lag=lag)
            rows.append({"ticker": ticker, "lag": lag, "acf": acf_val})

    if not rows:
        return pd.DataFrame()

    acf_df = pd.DataFrame(rows)
    mean_acf = acf_df.groupby("lag")["acf"].agg(["mean", "std"]).reset_index()
    mean_acf.columns = ["lag", "mean_acf", "std_acf"]

    # Significance band: ±1.96/sqrt(n)
    n_avg = sub.groupby("ticker").size().mean()
    mean_acf["sig_band"] = 1.96 / np.sqrt(n_avg)
    mean_acf["significant"] = mean_acf["mean_acf"].abs() > mean_acf["sig_band"]

    return mean_acf


def _sector_clustering(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """
    If 'sector' column is present, compute mean |resid| by sector.
    Otherwise attempts a heuristic GICS mapping from known tickers.
    """
    TICKER_SECTOR = {
        # Tech
        "AAPL": "Tech", "MSFT": "Tech", "NVDA": "Tech",
        "AMD": "Tech", "ORCL": "Tech",
        # Comm Services
        "GOOGL": "Comm", "META": "Comm", "NFLX": "Comm",
        # Consumer Disc
        "AMZN": "ConsDisc", "TSLA": "ConsDisc",
        "HD": "ConsDisc", "MCD": "ConsDisc",
        # Consumer Staples
        "PG": "ConsStap", "KO": "ConsStap",
        # Financials
        "MS": "Fin", "JPM": "Fin", "GS": "Fin", "BAC": "Fin",
        # Health Care
        "JNJ": "Health", "LLY": "Health", "ABBV": "Health",
        # Industrials
        "CAT": "Indust", "HON": "Indust", "BA": "Indust",
        # Energy
        "XOM": "Energy", "CVX": "Energy", "COP": "Energy",
        # Materials
        "LIN": "Materials",
        # Utilities
        "NEE": "Utilities",
        # Real Estate
        "AMT": "RealEstate",
    }

    sub = df[df["horizon"] == horizon].copy()
    sub["abs_resid"] = (sub["y_true"] - sub["y_pred"]).abs()
    sub["sector"] = sub["ticker"].map(TICKER_SECTOR).fillna("Other")

    by_sector = (
        sub.groupby("sector")
        .agg(
            mean_abs_resid=("abs_resid", "mean"),
            std_abs_resid=("abs_resid", "std"),
            n=("abs_resid", "count"),
        )
        .reset_index()
        .sort_values("mean_abs_resid", ascending=False)
    )

    # Kruskal-Wallis test across sectors
    groups = [sub[sub["sector"] == s]["abs_resid"].values
              for s in by_sector["sector"].unique()]
    if len(groups) >= 2:
        h_stat, p_val = stats.kruskal(*[g for g in groups if len(g) > 1])
        print(f"  Kruskal-Wallis H={h_stat:.2f}  p={p_val:.4f} "
              f"({'sectors differ' if p_val < 0.05 else 'no sector effect'})")

    return by_sector


def _residual_regime_breakdown(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """
    Bin signed residuals by calendar year and quarter.
    Identifies if errors are concentrated in specific macro regimes.
    """
    sub = df[df["horizon"] == horizon].copy()
    sub["signed_resid"] = sub["y_true"] - sub["y_pred"]
    sub["abs_resid"] = sub["signed_resid"].abs()
    sub["year"] = sub["date"].dt.year
    sub["quarter"] = sub["date"].dt.to_period("Q").astype(str)

    by_q = (
        sub.groupby("quarter")
        .agg(
            mean_abs_resid=("abs_resid", "mean"),
            mean_signed=("signed_resid", "mean"),
            n=("abs_resid", "count"),
        )
        .reset_index()
        .sort_values("quarter")
    )
    return by_q


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_residual_analysis(
    results_dir: Path,
    horizon: int = 21,
    top_n: int = 20,
    sigma_threshold: float = 2.0,
    output_dir: Path = None,
):
    output_dir = output_dir or results_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    df = _load_predictions(results_dir)
    available_horizons = sorted(df["horizon"].unique().tolist())
    print(f"[RESID] Available horizons: {available_horizons}")

    if horizon not in available_horizons:
        print(f"[RESID] H={horizon} not found. Using H={available_horizons[0]}")
        horizon = available_horizons[0]

    sub = df[df["horizon"] == horizon].copy()
    sub["signed_resid"] = sub["y_true"] - sub["y_pred"]
    sub["abs_resid"] = sub["signed_resid"].abs()

    n_obs = len(sub)
    n_tickers = sub["ticker"].nunique()
    mean_resid = sub["signed_resid"].mean()
    std_resid = sub["signed_resid"].std()

    print(f"\n[RESID] H={horizon}: {n_obs:,} obs across {n_tickers} tickers")
    print(f"        Mean signed resid: {mean_resid:.5f} "
          f"(bias: {'over' if mean_resid < 0 else 'under'}-predicts RV)")
    print(f"        Std of residuals:  {std_resid:.5f}")

    # ── 1. Worst dates ────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  1. Top-{top_n} Worst Prediction Dates (H={horizon})")
    print("=" * 60)
    worst = _worst_dates(df, horizon, top_n)
    print(worst.to_string(index=False))

    # ── 2. Cross-ticker clustering ─────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  2. Dates with >=3 Simultaneous Large Residuals "
          f"(|z|>{sigma_threshold}s, H={horizon})")
    print("     -> These are systematic shocks the model missed universally")
    print("=" * 60)
    clustered = _cross_ticker_clustering(df, horizon, sigma_threshold)
    if clustered.empty:
        print(f"  None found at {sigma_threshold}σ threshold.")
    else:
        print(clustered.to_string(index=False))
        print(f"\n  Found {len(clustered)} dates where the model failed cross-sectionally.")
        print("  Action: examine these dates for macro events not in current features.")

    # ── 3. Regime breakdown by quarter ────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  3. Error by Calendar Quarter (H={horizon})")
    print("=" * 60)
    regime = _residual_regime_breakdown(df, horizon)
    print(regime.to_string(index=False))

    # ── 4. Autocorrelation ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  4. Residual Autocorrelation (H={horizon})")
    print("     -> Significant ACF at lag 1-5 implies a missing trend/regime feature")
    print("=" * 60)
    acf_df = _autocorrelation(df, horizon)
    if acf_df.empty:
        print("  Insufficient data for ACF.")
    else:
        print(acf_df.to_string(index=False))
        sig_lags = acf_df[acf_df["significant"]]["lag"].tolist()
        if sig_lags:
            print(f"\n  Significant ACF at lags: {sig_lags}")
            print("  Action: add AR(k) vol features or regime indicator at these lags.")
        else:
            print("  No significant ACF — residuals appear white-noise. Good.")

    # ── 5. Sector clustering ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  5. Mean |Residual| by Sector (H={horizon})")
    print("=" * 60)
    sector = _sector_clustering(df, horizon)
    print(sector.to_string(index=False))

    # ── 6. Per-ticker residual summary ────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  6. Per-Ticker Residual Summary (H={horizon})")
    print("=" * 60)
    per_ticker = (
        sub.groupby("ticker")
        .agg(
            mean_signed=("signed_resid", "mean"),
            mean_abs=("abs_resid", "mean"),
            std=("signed_resid", "std"),
            n=("abs_resid", "count"),
        )
        .reset_index()
    )
    per_ticker["bias"] = per_ticker["mean_signed"].apply(
        lambda x: "over" if x < -0.001 else ("under" if x > 0.001 else "neutral")
    )
    per_ticker = per_ticker.sort_values("mean_abs", ascending=False)
    print(per_ticker.to_string(index=False))

    # ── Multi-horizon comparison ──────────────────────────────────────
    if len(available_horizons) > 1:
        print("\n" + "=" * 60)
        print("  7. Error Structure Across All Horizons")
        print("=" * 60)
        rows = []
        for h in available_horizons:
            h_sub = df[df["horizon"] == h].copy()
            h_sub["abs_resid"] = (h_sub["y_true"] - h_sub["y_pred"]).abs()
            h_sub["signed_resid"] = h_sub["y_true"] - h_sub["y_pred"]
            rows.append({
                "horizon": h,
                "n": len(h_sub),
                "mean_abs_resid": h_sub["abs_resid"].mean(),
                "std_resid": h_sub["signed_resid"].std(),
                "bias": h_sub["signed_resid"].mean(),
                "pct_large": (
                    _sigma_threshold_mask(h_sub["signed_resid"], sigma_threshold).mean()
                ),
            })
        print(pd.DataFrame(rows).to_string(index=False))

    # ── Save outputs ──────────────────────────────────────────────────
    worst.to_csv(output_dir / f"resid_worst_dates_H{horizon}.csv", index=False)
    if not clustered.empty:
        clustered.to_csv(
            output_dir / f"resid_cross_ticker_clusters_H{horizon}.csv", index=False
        )
    regime.to_csv(output_dir / f"resid_by_quarter_H{horizon}.csv", index=False)
    sector.to_csv(output_dir / f"resid_by_sector_H{horizon}.csv", index=False)
    per_ticker.to_csv(output_dir / f"resid_per_ticker_H{horizon}.csv", index=False)
    if not acf_df.empty:
        acf_df.to_csv(output_dir / f"resid_acf_H{horizon}.csv", index=False)

    print(f"\n[RESID] Outputs saved to {output_dir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Standalone residual diagnostic analysis"
    )
    parser.add_argument(
        "--predictions-dir", default="model/pipeline/results",
        help="Directory with backtest prediction CSVs"
    )
    parser.add_argument(
        "--horizon", type=int, default=21,
        help="Primary horizon to analyse (default: 21)"
    )
    parser.add_argument(
        "--top-n", type=int, default=20,
        help="Number of worst dates to report (default: 20)"
    )
    parser.add_argument(
        "--threshold", type=float, default=2.0,
        help="σ threshold for 'large' residual classification (default: 2.0)"
    )
    args = parser.parse_args()
    run_residual_analysis(
        results_dir=Path(args.predictions_dir),
        horizon=args.horizon,
        top_n=args.top_n,
        sigma_threshold=args.threshold,
    )


if __name__ == "__main__":
    main()

"""
vrp_analysis.py — VRP wedge bilateral uncertainty analysis.

Research question
-----------------
Does the *size* of the VRP wedge (IV - RV), treated as BILATERAL (we expect
|wedge| to signal uncertainty rather than direction), have statistically
significant implications for:

  (A) Subsequent realized volatility:   Is |wedge| a better predictor of RV
      than the model's point estimate?
  (B) Model prediction error:            Do larger |wedge| regimes produce
      larger absolute residuals?
  (C) Quintile-sorted RV lift:           Do observations in the top-quintile
      of |wedge| see reliably elevated future RV across all horizons?

Usage
-----
    python -m model.pipeline.analysis.vrp_analysis
    python -m model.pipeline.analysis.vrp_analysis --predictions-dir model/pipeline/results
    python -m model.pipeline.analysis.vrp_analysis --horizon 21 --n-quintiles 5
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import LinearRegression

from ..utils import DECIMAL_PRECISION, round_for_output


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_predictions(results_dir: Path) -> pd.DataFrame:
    """Load all_predictions.csv or concatenate per-ticker long-form files."""
    combined = results_dir / "all_predictions.csv"
    if combined.exists():
        df = pd.read_csv(combined, parse_dates=["date"])
        print(f"[VRP] Loaded {len(df):,} predictions from {combined.name}")
        return df

    # Fall back to per-ticker files (new schema: all horizons in one CSV).
    frames = []
    for f in sorted(results_dir.glob("predictions_*.csv")):
        if f.name == "all_predictions.csv":
            continue
        stem = f.stem
        parts = stem.split("_", 1)
        if len(parts) != 2 or parts[0] != "predictions":
            continue
        ticker = parts[1]
        df = pd.read_csv(f, parse_dates=["date"])
        if "ticker" not in df.columns:
            df["ticker"] = ticker
        frames.append(df)

    if not frames:
        print(f"[VRP] No prediction files found in {results_dir}")
        sys.exit(1)

    df = pd.concat(frames, ignore_index=True)
    print(f"[VRP] Loaded {len(df):,} predictions from {len(frames)} files")
    return df


def _quintile_stats(series: pd.Series, y: pd.Series, n: int = 5) -> pd.DataFrame:
    """
    Sort observations by *series* into *n* bins, report mean/median/std of y
    and a t-test vs the full sample mean.
    """
    labels = list(range(1, n + 1))
    bins = pd.qcut(series, q=n, labels=labels, duplicates="drop")
    rows = []
    full_mean = y.mean()
    for q in labels:
        mask = bins == q
        if mask.sum() < 5:
            continue
        sub = y[mask]
        t, p = stats.ttest_1samp(sub, full_mean)
        rows.append({
            "quintile": q,
            "n": int(mask.sum()),
            "mean": sub.mean(),
            "median": sub.median(),
            "std": sub.std(),
            "t_stat": t,
            "p_value": p,
            "sig": "*" if p < 0.05 else ("~" if p < 0.10 else ""),
        })
    return pd.DataFrame(rows)


def _ols_summary(x: np.ndarray, y: np.ndarray, x_label: str, y_label: str) -> dict:
    """Run OLS and return a summary dict."""
    x = x.reshape(-1, 1)
    lr = LinearRegression().fit(x, y)
    y_hat = lr.predict(x)
    ss_res = np.sum((y - y_hat) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 1e-12 else np.nan

    # t-stat for slope via scipy
    slope, intercept, r, p, se = stats.linregress(x.ravel(), y)

    return {
        "x": x_label,
        "y": y_label,
        "slope": slope,
        "intercept": intercept,
        "r2": r2,
        "t_stat": slope / se if se > 0 else np.nan,
        "p_value": p,
        "sig": "*" if p < 0.05 else ("~" if p < 0.10 else ""),
    }


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def run_vrp_analysis(
    results_dir: Path,
    horizon: int = 21,
    n_quintiles: int = 5,
    output_dir: Path = None,
):
    output_dir = output_dir or results_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    df = _load_predictions(results_dir)

    if "vrp_wedge" not in df.columns:
        print("[VRP] 'vrp_wedge' column not found in predictions. "
              "Re-run backtest with the updated backtest.py to populate it.")
        sys.exit(1)

    # Filter to horizon of interest; drop rows missing wedge or targets
    sub = df[df["horizon"] == horizon].copy()
    sub = sub.dropna(subset=["vrp_wedge", "y_true", "y_pred"])

    if sub.empty:
        print(f"[VRP] No data for H={horizon} after dropping NaNs.")
        sys.exit(1)

    print(f"\n[VRP] Analysing {len(sub):,} observations at H={horizon} "
          f"across {sub['ticker'].nunique()} tickers")
    print(f"      VRP wedge range: [{sub['vrp_wedge'].min():.4f}, "
          f"{sub['vrp_wedge'].max():.4f}]  "
          f"mean={sub['vrp_wedge'].mean():.4f}")

    # ── Bilateral transform ───────────────────────────────────────────────
    # |wedge| = size of dislocation regardless of direction
    sub["abs_wedge"] = sub["vrp_wedge"].abs()
    # Rolling 252-day percentile rank of |wedge| (regime-adjusted)
    sub = sub.sort_values("date")
    sub["abs_wedge_pct"] = sub["abs_wedge"].rank(pct=True)

    # Prediction residual (absolute and signed)
    sub["abs_resid"] = (sub["y_true"] - sub["y_pred"]).abs()
    sub["signed_resid"] = sub["y_true"] - sub["y_pred"]

    # ── A: Does |wedge| predict elevated RV? (OLS: y_true ~ |wedge|) ─────
    print("\n" + "=" * 60)
    print("  A. |VRP Wedge| vs Realized Volatility")
    print("=" * 60)

    ols_rv = _ols_summary(
        sub["abs_wedge"].values, sub["y_true"].values,
        "|vrp_wedge|", "y_true (RV)"
    )
    print(f"  OLS: y_true = {ols_rv['intercept']:.4f} + "
          f"{ols_rv['slope']:.4f} * |wedge|")
    print(f"  R²={ols_rv['r2']:.4f}  t={ols_rv['t_stat']:.2f}  "
          f"p={ols_rv['p_value']:.4f}  {ols_rv['sig']}")

    qt_rv = _quintile_stats(sub["abs_wedge"], sub["y_true"], n=n_quintiles)
    print(f"\n  Quintile sort on |wedge| -> mean realized vol:")
    print(qt_rv[["quintile", "n", "mean", "std", "t_stat", "p_value", "sig"]].to_string(index=False))

    # ── B: Does |wedge| predict model error? (OLS: |resid| ~ |wedge|) ────
    print("\n" + "=" * 60)
    print("  B. |VRP Wedge| vs |Prediction Error|")
    print("=" * 60)

    ols_err = _ols_summary(
        sub["abs_wedge"].values, sub["abs_resid"].values,
        "|vrp_wedge|", "|residual|"
    )
    print(f"  OLS: |resid| = {ols_err['intercept']:.4f} + "
          f"{ols_err['slope']:.4f} * |wedge|")
    print(f"  R²={ols_err['r2']:.4f}  t={ols_err['t_stat']:.2f}  "
          f"p={ols_err['p_value']:.4f}  {ols_err['sig']}")

    qt_err = _quintile_stats(sub["abs_wedge"], sub["abs_resid"], n=n_quintiles)
    print(f"\n  Quintile sort on |wedge| -> mean |residual|:")
    print(qt_err[["quintile", "n", "mean", "std", "t_stat", "p_value", "sig"]].to_string(index=False))

    # ── C: Quintile-sorted RV using percentile rank (regime-adjusted) ────
    print("\n" + "=" * 60)
    print("  C. |VRP Wedge| Percentile Rank -> Realized Vol (regime-adj)")
    print("=" * 60)

    qt_pct = _quintile_stats(sub["abs_wedge_pct"], sub["y_true"], n=n_quintiles)
    print(qt_pct[["quintile", "n", "mean", "std", "t_stat", "p_value", "sig"]].to_string(index=False))

    # ── D: Signed wedge — does direction matter? ─────────────────────────
    print("\n" + "=" * 60)
    print("  D. Signed VRP Wedge (IV - RV): Is direction informative?")
    print("     (If bilateral hypothesis holds, |wedge| should dominate)")
    print("=" * 60)

    ols_signed = _ols_summary(
        sub["vrp_wedge"].values, sub["y_true"].values,
        "vrp_wedge (signed)", "y_true (RV)"
    )
    print(f"  OLS signed: R²={ols_signed['r2']:.4f}  "
          f"t={ols_signed['t_stat']:.2f}  p={ols_signed['p_value']:.4f}  "
          f"{ols_signed['sig']}")
    print(f"  OLS bilateral: R²={ols_rv['r2']:.4f}  "
          f"t={ols_rv['t_stat']:.2f}  p={ols_rv['p_value']:.4f}  "
          f"{ols_rv['sig']}")
    diff = ols_rv["r2"] - ols_signed["r2"]
    print(f"  R² lift from |wedge| vs signed: {diff:+.4f} "
          f"({'bilateral wins' if diff > 0 else 'signed wins'})")

    # ── E: Per-ticker summary ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  E. Per-Ticker |Wedge| vs RV OLS (H={})".format(horizon))
    print("=" * 60)

    ticker_rows = []
    for ticker in sorted(sub["ticker"].unique()):
        t_sub = sub[sub["ticker"] == ticker]
        if len(t_sub) < 20:
            continue
        r = _ols_summary(
            t_sub["abs_wedge"].values, t_sub["y_true"].values,
            "|vrp_wedge|", "y_true"
        )
        r["ticker"] = ticker
        r["n"] = len(t_sub)
        ticker_rows.append(r)

    if ticker_rows:
        tk_df = pd.DataFrame(ticker_rows)[
            ["ticker", "n", "slope", "r2", "t_stat", "p_value", "sig"]
        ].sort_values("r2", ascending=False)
        print(tk_df.to_string(index=False))

    # ── F: put_call_skew_30d as downside supplement ───────────────────────
    if "put_call_skew_30d" in sub.columns:
        skew_sub = sub.dropna(subset=["put_call_skew_30d"])
        if len(skew_sub) >= 20:
            print("\n" + "=" * 60)
            print("  F. OTM Put-Call Skew (+/-0.25 delta) vs Realized Vol")
            print("=" * 60)
            ols_skew = _ols_summary(
                skew_sub["put_call_skew_30d"].values,
                skew_sub["y_true"].values,
                "put_call_skew_30d", "y_true (RV)"
            )
            print(f"  OLS: R²={ols_skew['r2']:.4f}  "
                  f"slope={ols_skew['slope']:.4f}  "
                  f"t={ols_skew['t_stat']:.2f}  "
                  f"p={ols_skew['p_value']:.4f}  {ols_skew['sig']}")
            print("  (Positive skew = OTM puts more expensive than calls -> "
                  "downside fear premium)")

            qt_skew = _quintile_stats(
                skew_sub["put_call_skew_30d"], skew_sub["y_true"], n=n_quintiles
            )
            print(f"\n  Quintile sort on skew -> mean RV:")
            print(qt_skew[
                ["quintile", "n", "mean", "std", "t_stat", "p_value", "sig"]
            ].to_string(index=False))

    # ── Save outputs ──────────────────────────────────────────────────────
    ols_rows = [ols_rv, ols_err, ols_signed, ols_skew if "put_call_skew_30d" in sub.columns else {}]
    ols_df = pd.DataFrame([r for r in ols_rows if r])
    round_for_output(ols_df, DECIMAL_PRECISION).to_csv(
        output_dir / f"vrp_ols_H{horizon}.csv", index=False,
    )

    qt_rv["analysis"] = "rv"
    qt_err["analysis"] = "error"
    qt_pct["analysis"] = "rv_pct_rank"
    quintile_combined = pd.concat([qt_rv, qt_err, qt_pct])
    round_for_output(quintile_combined, DECIMAL_PRECISION).to_csv(
        output_dir / f"vrp_quintiles_H{horizon}.csv", index=False,
    )
    if ticker_rows:
        round_for_output(tk_df, DECIMAL_PRECISION).to_csv(
            output_dir / f"vrp_per_ticker_H{horizon}.csv", index=False,
        )

    print(f"\n[VRP] Results saved to {output_dir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="VRP wedge bilateral uncertainty analysis"
    )
    parser.add_argument(
        "--predictions-dir", default="model/pipeline/results",
        help="Directory containing backtest predictions (default: model/pipeline/results)"
    )
    parser.add_argument(
        "--horizon", type=int, default=21,
        help="Forecast horizon to analyse (default: 21)"
    )
    parser.add_argument(
        "--n-quintiles", type=int, default=5,
        help="Number of quantile bins (default: 5)"
    )
    args = parser.parse_args()
    run_vrp_analysis(
        results_dir=Path(args.predictions_dir),
        horizon=args.horizon,
        n_quintiles=args.n_quintiles,
    )


if __name__ == "__main__":
    main()

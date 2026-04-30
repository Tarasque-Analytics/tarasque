"""
audit.py — Comprehensive model validity & performance audit.

Runs 9 post-hoc tests on existing prediction files. No backtest re-run
required. Prints results to stdout and saves CSV summaries to
model/pipeline/results/audit/.

Tests
-----
  1. MZ Regression         — alpha≈0, beta≈1 calibration, full 98-ticker universe
  2. Diebold-Mariano        — model vs lag-1 persistence baseline
  3. Tail Error Asymmetry   — RMSE / QLIKE top vs bottom 10% of realized vol
  4. Macro Regime Bias      — mean bias across COVID / rate-shock / post-norm regimes
  5. VRP Quintile RMSE      — conditional RMSE sorted by |VRP wedge| quintile
  6. Lasso Cross-Ticker     — Spearman rank correlation of feature inclusion across tickers
  7. VRP NaN Rate           — vrp_wedge NaN fraction per ticker (NaN propagation proxy)
  8. Term Structure         — H21 > H63 inversion rate per ticker
  9. Seam Analysis          — prediction jump distribution at model refit boundaries

QLIKE definition (consistent with backtest.py):
    QLIKE(y, yhat) = mean(y/yhat - log(y/yhat) - 1)
    Equal to 0 at perfect forecast; penalises underprediction more than over.

Usage
-----
    python -m model.pipeline.analysis.audit
    python -m model.pipeline.analysis.audit --predictions-dir model/pipeline/results
    python -m model.pipeline.analysis.audit --horizons 21 63 --tickers AAPL JPM XOM
"""
import argparse
import sys
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import LinearRegression

warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STEP_DAYS = 25  # WFA refit cadence (trading days)

MACRO_REGIMES = {
    "covid":      ("2020-02-01", "2020-09-30"),
    "rate_shock": ("2022-01-01", "2022-12-31"),
    "post_norm":  ("2023-01-01", "2024-12-31"),
}


def _qlike(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """QLIKE = mean(r - log(r) - 1) where r = y_true/y_pred."""
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = y_true / y_pred
        valid = np.isfinite(ratio) & (ratio > 0)
        if valid.sum() < 2:
            return np.nan
        r = ratio[valid]
        return float(np.mean(r - np.log(r) - 1))


def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def _section(title: str, width: int = 64) -> None:
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def _load_all_predictions(
    results_dir: Path,
    horizons: Optional[List[int]] = None,
    tickers: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Load all per-ticker prediction CSVs, parse ticker/horizon from filenames."""
    frames = []
    for f in sorted(results_dir.glob("predictions_*_H*.csv")):
        stem = f.stem  # e.g. predictions_AAPL_H21
        parts = stem.split("_")
        if len(parts) < 3:
            continue
        ticker = parts[1]
        try:
            horizon = int(parts[2][1:])  # "H21" -> 21
        except ValueError:
            continue
        if horizons and horizon not in horizons:
            continue
        if tickers and ticker not in tickers:
            continue
        df = pd.read_csv(f, parse_dates=["date"])
        df["ticker"] = ticker
        df["horizon"] = horizon
        frames.append(df)

    if not frames:
        print(f"[AUDIT] No prediction files found in {results_dir}")
        sys.exit(1)

    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["y_true", "y_pred"])
    # Guard against zero/negative predictions
    df = df[(df["y_pred"] > 0) & (df["y_true"] > 0)]
    print(f"[AUDIT] Loaded {len(df):,} predictions  |  "
          f"{df['ticker'].nunique()} tickers  |  "
          f"horizons {sorted(df['horizon'].unique())}")
    return df


# ---------------------------------------------------------------------------
# Test 1 – MZ Regression
# ---------------------------------------------------------------------------

def test_mz_regression(df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    """Mincer-Zarnowitz: y_true = alpha + beta*y_pred per (ticker, horizon)."""
    _section("TEST 1 - MZ Regression  (alpha~0, beta~1)")

    rows = []
    for (ticker, horizon), g in df.groupby(["ticker", "horizon"]):
        if len(g) < 20:
            continue
        y = g["y_true"].values
        yh = g["y_pred"].values
        lr = LinearRegression().fit(yh.reshape(-1, 1), y)
        alpha = lr.intercept_
        beta = lr.coef_[0]
        r2 = lr.score(yh.reshape(-1, 1), y)
        # t-test: is beta == 1?
        _, _, _, _, se_beta = stats.linregress(yh, y)
        t_beta1 = (beta - 1.0) / se_beta if se_beta > 0 else np.nan
        p_beta1 = 2 * stats.t.sf(abs(t_beta1), df=len(g) - 2)
        rows.append({
            "ticker": ticker, "horizon": horizon,
            "alpha": alpha, "beta": beta, "r2": r2,
            "t_beta1": t_beta1, "p_beta1": p_beta1,
            "n": len(g),
        })

    result = pd.DataFrame(rows)

    for h in sorted(result["horizon"].unique()):
        sub = result[result["horizon"] == h]
        n_well = ((sub["beta"] > 0.8) & (sub["beta"] < 1.2) & (sub["p_beta1"] > 0.05)).sum()
        print(f"\n  H={h} | {len(sub)} tickers  "
              f"| beta well-calibrated (0.8–1.2, p>0.05): {n_well}/{len(sub)}")
        # Show extremes
        bad = sub[sub["p_beta1"] < 0.05].sort_values("beta")
        if len(bad):
            print(f"    Tickers with beta!=1 (p<0.05):")
            for _, r in bad.iterrows():
                flag = "OVER" if r["beta"] > 1 else "UNDER"
                print(f"      {r['ticker']:6s}  beta={r['beta']:.3f} ({flag})  "
                      f"alpha={r['alpha']:.4f}  R²={r['r2']:.3f}")

    result.to_csv(out_dir / "mz_regression.csv", index=False)
    print(f"\n  Saved → audit/mz_regression.csv")
    return result


# ---------------------------------------------------------------------------
# Test 2 – Diebold-Mariano vs lag-1 persistence
# ---------------------------------------------------------------------------

def test_diebold_mariano(df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    """DM test: model vs lag-H persistence baseline, per (ticker, horizon).

    Naive forecast: y_true shifted by H rows. This uses the previous
    non-overlapping realized vol window as the forecast, matching the
    forecast horizon. Shifting by 1 row would use overlapping windows
    (20/21 days shared at H=21) which artificially lowers naive RMSE.
    """
    _section("TEST 2 · Diebold-Mariano  (model vs lag-H persistence)")
    print("  loss = squared error  |  negative DM -> model beats naive")
    print("  naive = y_true shifted by H rows (non-overlapping window persistence)")

    rows = []
    for (ticker, horizon), g in df.groupby(["ticker", "horizon"]):
        g = g.sort_values("date").reset_index(drop=True)
        if len(g) < horizon + 30:
            continue
        # Naive: shift by H rows = previous non-overlapping realized vol window
        naive = g["y_true"].shift(horizon)
        valid = ~naive.isna()
        g = g[valid]
        naive = naive[valid]

        y = g["y_true"].values
        yh_model = g["y_pred"].values
        yh_naive = naive.values

        e_model = y - yh_model
        e_naive = y - yh_naive

        # Squared loss
        d_sq = e_model ** 2 - e_naive ** 2
        n = len(d_sq)
        dm_sq = np.mean(d_sq) / (np.std(d_sq, ddof=1) / np.sqrt(n))

        # QLIKE loss
        q_model = np.array([
            r - np.log(r) - 1 if (r := yt / yh) > 0 else np.nan
            for yt, yh in zip(y, yh_model)
        ])
        q_naive = np.array([
            r - np.log(r) - 1 if (r := yt / yh) > 0 else np.nan
            for yt, yh in zip(y, yh_naive)
        ])
        valid_q = np.isfinite(q_model) & np.isfinite(q_naive)
        d_ql = q_model[valid_q] - q_naive[valid_q]
        dm_ql = (np.mean(d_ql) / (np.std(d_ql, ddof=1) / np.sqrt(valid_q.sum()))
                 if valid_q.sum() > 1 else np.nan)

        p_sq = 2 * stats.t.sf(abs(dm_sq), df=n - 1)
        p_ql = 2 * stats.t.sf(abs(dm_ql), df=valid_q.sum() - 1) if np.isfinite(dm_ql) else np.nan

        rows.append({
            "ticker": ticker, "horizon": horizon,
            "dm_sq": dm_sq, "p_sq": p_sq,
            "dm_ql": dm_ql, "p_ql": p_ql,
            "model_rmse": _rmse(y, yh_model),
            "naive_rmse": _rmse(y, yh_naive),
            "model_qlike": _qlike(y, yh_model),
            "naive_qlike": _qlike(y, yh_naive),
            "n": n,
        })

    result = pd.DataFrame(rows)

    for h in sorted(result["horizon"].unique()):
        sub = result[result["horizon"] == h]
        n_beats = (sub["dm_sq"] < -1.96).sum()
        n_loses = (sub["dm_sq"] > 1.96).sum()
        avg_lift = (sub["naive_rmse"] - sub["model_rmse"]).mean()
        print(f"\n  H={h} | Model beats naive (p<0.05): {n_beats}/{len(sub)}  "
              f"| Loses: {n_loses}/{len(sub)}  "
              f"| Avg RMSE lift: {avg_lift:+.4f}")
        # Show failures
        loses = sub[sub["dm_sq"] > 1.96].sort_values("dm_sq", ascending=False)
        if len(loses):
            print(f"    Tickers where naive beats model:")
            for _, r in loses.iterrows():
                print(f"      {r['ticker']:6s}  DM={r['dm_sq']:.2f}  "
                      f"model_rmse={r['model_rmse']:.4f}  naive={r['naive_rmse']:.4f}")

    result.to_csv(out_dir / "diebold_mariano.csv", index=False)
    print(f"\n  Saved → audit/diebold_mariano.csv")
    return result


# ---------------------------------------------------------------------------
# Test 3 – Tail Error Asymmetry
# ---------------------------------------------------------------------------

def test_tail_asymmetry(df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    """RMSE and QLIKE broken out by top/bottom 10% of realized vol."""
    _section("TEST 3 · Tail Error Asymmetry  (top/bottom 10% y_true)")

    rows = []
    for (ticker, horizon), g in df.groupby(["ticker", "horizon"]):
        if len(g) < 30:
            continue
        p10 = g["y_true"].quantile(0.10)
        p90 = g["y_true"].quantile(0.90)

        for label, mask in [
            ("bottom_10", g["y_true"] <= p10),
            ("middle_80", (g["y_true"] > p10) & (g["y_true"] < p90)),
            ("top_10",    g["y_true"] >= p90),
        ]:
            sub = g[mask]
            if len(sub) < 5:
                continue
            rows.append({
                "ticker": ticker, "horizon": horizon, "bucket": label,
                "n": len(sub),
                "rmse": _rmse(sub["y_true"].values, sub["y_pred"].values),
                "qlike": _qlike(sub["y_true"].values, sub["y_pred"].values),
                "mean_y_true": sub["y_true"].mean(),
                "mean_y_pred": sub["y_pred"].mean(),
                "mean_bias": (sub["y_pred"] - sub["y_true"]).mean(),
            })

    result = pd.DataFrame(rows)

    for h in sorted(result["horizon"].unique()):
        sub = result[result["horizon"] == h]
        print(f"\n  H={h} — median RMSE by bucket:")
        summary = sub.groupby("bucket")[["rmse", "qlike", "mean_bias"]].median()
        print(summary.to_string())

        # Flag: how many tickers have tail RMSE > 2× median RMSE?
        pivot = sub.pivot_table(index="ticker", columns="bucket", values="rmse")
        if "top_10" in pivot.columns and "middle_80" in pivot.columns:
            ratio = pivot["top_10"] / pivot["middle_80"]
            n_high = (ratio > 3.0).sum()
            print(f"\n  Tickers where top-10 RMSE > 3× middle-80 RMSE: {n_high}")

    result.to_csv(out_dir / "tail_asymmetry.csv", index=False)
    print(f"\n  Saved → audit/tail_asymmetry.csv")
    return result


# ---------------------------------------------------------------------------
# Test 4 – Macro Regime Bias
# ---------------------------------------------------------------------------

def test_regime_bias(df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    """Mean bias and RMSE split by COVID / rate-shock / post-norm / normal."""
    _section("TEST 4 · Macro Regime Bias")

    df = df.copy()
    df["regime"] = "normal"
    for name, (start, end) in MACRO_REGIMES.items():
        mask = (df["date"] >= start) & (df["date"] <= end)
        df.loc[mask, "regime"] = name

    df["bias"] = df["y_pred"] - df["y_true"]
    df["abs_err"] = df["bias"].abs()

    rows = []
    for (horizon, regime), g in df.groupby(["horizon", "regime"]):
        rows.append({
            "horizon": horizon, "regime": regime,
            "n": len(g),
            "mean_bias": g["bias"].mean(),
            "rmse": _rmse(g["y_true"].values, g["y_pred"].values),
            "qlike": _qlike(g["y_true"].values, g["y_pred"].values),
            "mean_y_true": g["y_true"].mean(),
        })

    result = pd.DataFrame(rows)

    for h in sorted(result["horizon"].unique()):
        sub = result[result["horizon"] == h].sort_values("regime")
        print(f"\n  H={h}:")
        print(sub[["regime", "n", "mean_bias", "rmse", "qlike", "mean_y_true"]].to_string(index=False))

    # Per-ticker regime bias for H=21 only
    ticker_rows = []
    h21 = df[df["horizon"] == 21].copy()
    for (ticker, regime), g in h21.groupby(["ticker", "regime"]):
        if len(g) < 5:
            continue
        ticker_rows.append({
            "ticker": ticker, "regime": regime,
            "mean_bias": g["bias"].mean(),
            "n": len(g),
        })

    if ticker_rows:
        per_ticker = pd.DataFrame(ticker_rows)
        per_ticker.to_csv(out_dir / "regime_bias_per_ticker_H21.csv", index=False)
        print(f"\n  Per-ticker H=21 regime bias → audit/regime_bias_per_ticker_H21.csv")

    result.to_csv(out_dir / "regime_bias.csv", index=False)
    print(f"  Saved → audit/regime_bias.csv")
    return result


# ---------------------------------------------------------------------------
# Test 5 – VRP Quintile Conditional RMSE
# ---------------------------------------------------------------------------

def test_vrp_quintile_rmse(df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    """RMSE and bias per quintile of |VRP wedge|."""
    _section("TEST 5 · VRP Quintile Conditional RMSE")

    if "vrp_wedge" not in df.columns:
        print("  [SKIP] vrp_wedge column not present")
        return pd.DataFrame()

    sub = df.dropna(subset=["vrp_wedge"]).copy()
    sub["abs_wedge"] = sub["vrp_wedge"].abs()

    rows = []
    for horizon in sorted(sub["horizon"].unique()):
        h_sub = sub[sub["horizon"] == horizon].copy()
        if len(h_sub) < 25:
            continue
        h_sub["quintile"] = pd.qcut(h_sub["abs_wedge"], q=5, labels=[1, 2, 3, 4, 5],
                                    duplicates="drop")
        for q in [1, 2, 3, 4, 5]:
            g = h_sub[h_sub["quintile"] == q]
            if len(g) < 5:
                continue
            rows.append({
                "horizon": horizon, "quintile": q, "n": len(g),
                "mean_abs_wedge": g["abs_wedge"].mean(),
                "rmse": _rmse(g["y_true"].values, g["y_pred"].values),
                "qlike": _qlike(g["y_true"].values, g["y_pred"].values),
                "mean_bias": (g["y_pred"] - g["y_true"]).mean(),
            })

    result = pd.DataFrame(rows)

    for h in sorted(result["horizon"].unique()):
        sub_h = result[result["horizon"] == h]
        print(f"\n  H={h}:")
        print(sub_h[["quintile", "n", "mean_abs_wedge", "rmse", "qlike", "mean_bias"]].to_string(index=False))

    result.to_csv(out_dir / "vrp_quintile_rmse.csv", index=False)
    print(f"\n  Saved → audit/vrp_quintile_rmse.csv")
    return result


# ---------------------------------------------------------------------------
# Test 6 – Lasso Cross-Ticker Stability
# ---------------------------------------------------------------------------

def test_lasso_stability(results_dir: Path, out_dir: Path) -> Optional[pd.DataFrame]:
    """Spearman rank correlation of feature inclusion_freq across tickers."""
    _section("TEST 6 · Lasso Cross-Ticker Feature Stability")

    lasso_files = sorted(results_dir.glob("lasso_tracking_*.csv"))
    if not lasso_files:
        print("  [SKIP] No lasso_tracking_*.csv files found")
        return None

    print(f"  Found {len(lasso_files)} lasso tracking files")

    frames = []
    for f in lasso_files:
        ticker = f.stem.split("_")[-1]
        df = pd.read_csv(f)
        df["ticker"] = ticker
        frames.append(df)

    all_lasso = pd.concat(frames, ignore_index=True)
    rows = []

    for horizon in sorted(all_lasso["horizon"].unique()):
        h_data = all_lasso[all_lasso["horizon"] == horizon]
        pivot = h_data.pivot_table(
            index="feature", columns="ticker", values="inclusion_freq"
        ).fillna(0)

        tickers = list(pivot.columns)
        n = len(tickers)
        corr_matrix = np.zeros((n, n))
        for i in range(n):
            for j in range(i, n):
                r, _ = stats.spearmanr(pivot.iloc[:, i], pivot.iloc[:, j])
                corr_matrix[i, j] = corr_matrix[j, i] = r

        # Average off-diagonal correlation = stability score
        upper = corr_matrix[np.triu_indices(n, k=1)]
        stability = upper.mean() if len(upper) > 0 else np.nan

        print(f"\n  H={horizon} | {n} tickers | Avg pairwise Spearman rank corr = {stability:.3f}")

        # Top 10 features by mean inclusion
        top = h_data.groupby("feature")["inclusion_freq"].mean().sort_values(ascending=False).head(10)
        print(f"  Top 10 features (mean inclusion freq):")
        for feat, freq in top.items():
            print(f"    {feat:40s}  {freq:.3f}")

        rows.append({
            "horizon": horizon,
            "n_tickers": n,
            "avg_spearman": stability,
        })

        # Correlation matrix
        corr_df = pd.DataFrame(corr_matrix, index=tickers, columns=tickers)
        corr_df.to_csv(out_dir / f"lasso_rank_corr_H{horizon}.csv")

    result = pd.DataFrame(rows)
    result.to_csv(out_dir / "lasso_stability.csv", index=False)
    print(f"\n  Saved → audit/lasso_stability.csv + lasso_rank_corr_H*.csv")
    return result


# ---------------------------------------------------------------------------
# Test 7 – VRP NaN Rate
# ---------------------------------------------------------------------------

def test_vrp_nan_rate(results_dir: Path, out_dir: Path) -> pd.DataFrame:
    """vrp_wedge NaN fraction per ticker — proxy for data pipeline completeness."""
    _section("TEST 7 · VRP Wedge NaN Rate (NaN Propagation Proxy)")

    # Load raw H=21 files to get vrp_wedge NaN counts
    rows = []
    for f in sorted(results_dir.glob("predictions_*_H21.csv")):
        parts = f.stem.split("_")
        ticker = parts[1]
        df = pd.read_csv(f)
        n = len(df)
        if "vrp_wedge" not in df.columns:
            nan_rate = 1.0
        else:
            nan_rate = df["vrp_wedge"].isna().mean()
        rows.append({"ticker": ticker, "n": n, "vrp_nan_rate": nan_rate})

    result = pd.DataFrame(rows).sort_values("vrp_nan_rate", ascending=False)

    # Summary
    n_zero = (result["vrp_nan_rate"] == 0).sum()
    n_high = (result["vrp_nan_rate"] > 0.10).sum()
    print(f"\n  {len(result)} tickers  |  "
          f"{n_zero} with 0% NaN  |  {n_high} with >10% NaN")

    # Show tickers with high NaN rate
    high = result[result["vrp_nan_rate"] > 0.05]
    if len(high):
        print(f"\n  Tickers with vrp_wedge NaN rate > 5%:")
        print(high[["ticker", "n", "vrp_nan_rate"]].to_string(index=False))
    else:
        print("  All tickers have vrp_wedge NaN rate ≤ 5%")

    result.to_csv(out_dir / "vrp_nan_rate.csv", index=False)
    print(f"\n  Saved → audit/vrp_nan_rate.csv")
    return result


# ---------------------------------------------------------------------------
# Test 8 – Term Structure Inversion Rate
# ---------------------------------------------------------------------------

def test_term_structure(df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    """H21 pred > H63 pred (inversion) rate per ticker."""
    _section("TEST 8 · Term Structure Inversion Rate  (H21 > H63)")

    has_h21 = df[df["horizon"] == 21][["date", "ticker", "y_pred"]].rename(
        columns={"y_pred": "pred_21"}
    )
    has_h63 = df[df["horizon"] == 63][["date", "ticker", "y_pred"]].rename(
        columns={"y_pred": "pred_63"}
    )
    has_h126 = df[df["horizon"] == 126][["date", "ticker", "y_pred"]].rename(
        columns={"y_pred": "pred_126"}
    )

    merged = (
        has_h21
        .merge(has_h63, on=["date", "ticker"], how="inner")
        .merge(has_h126, on=["date", "ticker"], how="inner")
    )

    if merged.empty:
        print("  [SKIP] Cannot merge horizons (no common dates)")
        return pd.DataFrame()

    merged["inv_21_63"]  = merged["pred_21"] > merged["pred_63"]
    merged["inv_63_126"] = merged["pred_63"] > merged["pred_126"]
    merged["inv_any"]    = merged["inv_21_63"] | merged["inv_63_126"]

    rows = []
    for ticker, g in merged.groupby("ticker"):
        rows.append({
            "ticker": ticker,
            "n": len(g),
            "inv_21_63_rate": g["inv_21_63"].mean(),
            "inv_63_126_rate": g["inv_63_126"].mean(),
            "inv_any_rate": g["inv_any"].mean(),
        })

    result = pd.DataFrame(rows).sort_values("inv_any_rate", ascending=False)

    # Overall
    overall_inv = merged["inv_any"].mean()
    overall_21_63 = merged["inv_21_63"].mean()
    print(f"\n  {len(merged):,} matched (date, ticker) pairs")
    print(f"  Overall inversion rate (any):  {overall_inv:.3f}")
    print(f"  H21 > H63 inversion rate:      {overall_21_63:.3f}")
    print(f"  H63 > H126 inversion rate:     {merged['inv_63_126'].mean():.3f}")

    high = result[result["inv_any_rate"] > 0.20]
    if len(high):
        print(f"\n  Tickers with >20% any-inversion:")
        print(high[["ticker", "n", "inv_21_63_rate", "inv_63_126_rate"]].to_string(index=False))

    result.to_csv(out_dir / "term_structure.csv", index=False)
    print(f"\n  Saved → audit/term_structure.csv")
    return result


# ---------------------------------------------------------------------------
# Test 9 – Seam Analysis
# ---------------------------------------------------------------------------

def test_seam_analysis(df: pd.DataFrame, out_dir: Path,
                       step_days: int = STEP_DAYS) -> pd.DataFrame:
    """
    Detect model refit boundaries (seams) via day-over-day |Δy_pred|.
    Seam dates occur every ~step_days trading days per (ticker, horizon).
    Checks whether prediction jumps cluster at step boundaries.
    """
    _section(f"TEST 9 · Prediction Seam Analysis  (step_days={step_days})")

    rows = []
    for (ticker, horizon), g in df.groupby(["ticker", "horizon"]):
        g = g.sort_values("date").reset_index(drop=True)
        if len(g) < step_days + 5:
            continue

        g["delta"] = g["y_pred"].diff().abs()
        g = g.dropna(subset=["delta"])

        if len(g) < 2:
            continue

        delta = g["delta"].values
        median_delta = np.median(delta)
        p95_delta = np.percentile(delta, 95)

        # Flag rows at expected seam positions (multiples of step_days ± 3)
        indices = np.arange(len(g))
        is_seam = np.zeros(len(g), dtype=bool)
        for step_idx in range(step_days, len(g), step_days):
            lo, hi = max(0, step_idx - 3), min(len(g), step_idx + 4)
            is_seam[lo:hi] = True

        seam_delta = delta[is_seam]
        non_seam_delta = delta[~is_seam]

        if len(seam_delta) < 5 or len(non_seam_delta) < 5:
            continue

        # Mann-Whitney U: are seam-position jumps larger than off-seam?
        u_stat, p_mw = stats.mannwhitneyu(seam_delta, non_seam_delta, alternative="greater")
        rows.append({
            "ticker": ticker, "horizon": horizon,
            "n": len(g),
            "median_delta": median_delta,
            "p95_delta": p95_delta,
            "seam_median_delta": np.median(seam_delta),
            "off_seam_median_delta": np.median(non_seam_delta),
            "seam_ratio": np.median(seam_delta) / np.median(non_seam_delta)
                          if np.median(non_seam_delta) > 0 else np.nan,
            "p_mw": p_mw,
        })

    result = pd.DataFrame(rows)

    for h in sorted(result["horizon"].unique()):
        sub = result[result["horizon"] == h]
        med_ratio = sub["seam_ratio"].median()
        n_sig = (sub["p_mw"] < 0.05).sum()
        print(f"\n  H={h} | Median seam/off-seam jump ratio: {med_ratio:.2f}  "
              f"| Significant seam effect (p<0.05): {n_sig}/{len(sub)} tickers")

    # Overall jump distribution
    print(f"\n  Interpretation guide:")
    print(f"    ratio ≈ 1.0 → smooth predictions, no seam artifacts")
    print(f"    ratio > 2.0 → visible model refit jumps at step boundaries")
    print(f"    ratio > 5.0 → severe discontinuities (investigate)")

    result.to_csv(out_dir / "seam_analysis.csv", index=False)
    print(f"\n  Saved → audit/seam_analysis.csv")
    return result


# ---------------------------------------------------------------------------
# Summary verdict
# ---------------------------------------------------------------------------

def _print_verdict(
    mz: pd.DataFrame,
    dm: pd.DataFrame,
    regime: pd.DataFrame,
    term: pd.DataFrame,
    seam: pd.DataFrame,
) -> None:
    _section("AUDIT VERDICT", width=64)

    # MZ calibration
    well = ((mz["beta"] > 0.8) & (mz["beta"] < 1.2) & (mz["p_beta1"] > 0.05))
    pct_well = well.mean() * 100
    print(f"  Calibration (MZ beta 0.8–1.2):  {pct_well:.0f}% of (ticker,horizon) pairs")

    # DM wins
    h21 = dm[dm["horizon"] == 21] if not dm.empty else pd.DataFrame()
    if not h21.empty:
        beats = (h21["dm_sq"] < -1.96).mean() * 100
        print(f"  DM test H=21: model beats naive in {beats:.0f}% of tickers")

    # Regime bias
    if not regime.empty:
        covid_bias = regime[regime["regime"] == "covid"]["mean_bias"].mean()
        print(f"  COVID mean bias (all tickers, all H): {covid_bias:+.4f} (+ = overpred)")

    # Term structure
    if not term.empty:
        inv = term["inv_any_rate"].mean()
        print(f"  Term structure inversion rate (any): {inv:.3f}")

    # Seam
    if not seam.empty:
        h21_seam = seam[seam["horizon"] == 21]
        if not h21_seam.empty:
            med_ratio = h21_seam["seam_ratio"].median()
            print(f"  Seam jump ratio H=21: {med_ratio:.2f}  "
                  f"({'clean' if med_ratio < 2 else 'noticeable' if med_ratio < 4 else 'HIGH'})")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Tarasque model audit")
    parser.add_argument("--predictions-dir", default="model/pipeline/results")
    parser.add_argument("--lasso-dir", default=None,
                        help="Directory with lasso_tracking_*.csv (default: predictions-dir)")
    parser.add_argument("--output-dir", default=None,
                        help="Where to write audit CSVs (default: predictions-dir/audit)")
    parser.add_argument("--horizons", type=int, nargs="+", default=None,
                        help="Limit to specific horizons, e.g. --horizons 21 63")
    parser.add_argument("--tickers", nargs="+", default=None,
                        help="Limit to specific tickers")
    args = parser.parse_args()

    results_dir = Path(args.predictions_dir)
    lasso_dir = Path(args.lasso_dir) if args.lasso_dir else results_dir
    out_dir = Path(args.output_dir) if args.output_dir else results_dir / "audit"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*64}")
    print(f"  Tarasque Model Audit")
    print(f"  Predictions dir: {results_dir}")
    print(f"  Output dir:      {out_dir}")
    print(f"{'='*64}")

    df = _load_all_predictions(results_dir, args.horizons, args.tickers)

    mz     = test_mz_regression(df, out_dir)
    dm     = test_diebold_mariano(df, out_dir)
    tail   = test_tail_asymmetry(df, out_dir)
    regime = test_regime_bias(df, out_dir)
    vrp    = test_vrp_quintile_rmse(df, out_dir)
    lasso  = test_lasso_stability(lasso_dir, out_dir)
    nan_r  = test_vrp_nan_rate(results_dir, out_dir)
    term   = test_term_structure(df, out_dir)
    seam   = test_seam_analysis(df, out_dir)

    _print_verdict(mz, dm, regime, term, seam)

    print(f"\n[AUDIT] Complete. Results in {out_dir}\n")


if __name__ == "__main__":
    main()

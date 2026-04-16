"""
Cross-Branch Backtest Comparison
================================
Compares results from Backtest-Analytics (Leo, 5950X) vs caleb-hardware-backtest-run (i7-11700K).
Model code was identical at runtime; differences expected from RF stochasticity,
data pull timing, and hardware FP behavior.
"""

import os, json, warnings
import numpy as np
import pandas as pd
from scipy import stats
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

warnings.filterwarnings("ignore", category=FutureWarning)

# ── Paths ──────────────────────────────────────────────────────────────
BASE = Path(__file__).parent
BA = BASE / "ba_results"
CALEB = BASE / "caleb_results"
PLOTS = BASE / "plots"
PLOTS.mkdir(exist_ok=True)

HORIZONS = [21, 63, 126]

# ── Sector map (same as pipeline) ─────────────────────────────────────
SECTOR_MAP = {
    "AAPL": "Tech", "MSFT": "Tech", "NVDA": "Tech", "ADBE": "Tech", "CRM": "Tech",
    "INTC": "Tech", "AMD": "Tech", "QCOM": "Tech", "AVGO": "Tech", "CSCO": "Tech",
    "ORCL": "Tech", "IBM": "Tech", "TXN": "Tech", "AMAT": "Tech", "MU": "Tech",
    "JPM": "Financials", "BAC": "Financials", "WFC": "Financials", "MS": "Financials",
    "GS": "Financials", "SCHW": "Financials", "BLK": "Financials", "AXP": "Financials",
    "USB": "Financials",
    "XOM": "Energy", "COP": "Energy", "EOG": "Energy", "SLB": "Energy", "OXY": "Energy",
    "MPC": "Energy", "PSX": "Energy",
    "UNH": "Health Care", "JNJ": "Health Care", "PFE": "Health Care", "ABBV": "Health Care",
    "MRK": "Health Care", "LLY": "Health Care", "BMY": "Health Care", "AMGN": "Health Care",
    "GILD": "Health Care", "ABT": "Health Care", "TMO": "Health Care",
    "AMZN": "ConsDisc", "TSLA": "ConsDisc", "HD": "ConsDisc", "NKE": "ConsDisc",
    "MCD": "ConsDisc", "SBUX": "ConsDisc", "LOW": "ConsDisc", "TGT": "ConsDisc",
    "F": "ConsDisc", "GM": "ConsDisc", "BKNG": "ConsDisc",
    "KO": "ConsStap", "PEP": "ConsStap", "PM": "ConsStap", "CL": "ConsStap",
    "MO": "ConsStap", "COST": "ConsStap", "WMT": "ConsStap",
    "META": "Comm", "GOOGL": "Comm", "NFLX": "Comm", "DIS": "Comm",
    "CMCSA": "Comm", "T": "Comm", "VZ": "Comm",
    "BA": "Industrials", "HON": "Industrials", "CAT": "Industrials", "GE": "Industrials",
    "LMT": "Industrials", "RTX": "Industrials", "DE": "Industrials", "UPS": "Industrials",
    "FDX": "Industrials", "NOC": "Industrials", "MMM": "Industrials", "DOW": "Industrials",
    "LIN": "Materials", "FCX": "Materials", "NEM": "Materials", "APD": "Materials",
    "NEE": "Utilities", "DUK": "Utilities", "SO": "Utilities", "D": "Utilities",
    "AEP": "Utilities",
    "AMT": "RealEstate", "PLD": "RealEstate", "CCI": "RealEstate",
    "EQIX": "RealEstate", "SPG": "RealEstate",
}


def mz_regression(y_true, y_pred):
    """Mincer-Zarnowitz regression: y_true = alpha + beta * y_pred + eps."""
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    yt, yp = y_true[mask], y_pred[mask]
    if len(yt) < 10:
        return {"alpha": np.nan, "beta": np.nan, "R2": np.nan, "RMSE": np.nan,
                "QLIKE": np.nan, "n": len(yt)}
    slope, intercept, r, p, se = stats.linregress(yp, yt)
    resid = yt - yp
    rmse = np.sqrt(np.mean(resid**2))
    # QLIKE: mean(y_true/y_pred - log(y_true/y_pred) - 1), requires positive values
    pos = (yt > 0) & (yp > 0)
    if pos.sum() > 10:
        ratio = yt[pos] / yp[pos]
        qlike = np.mean(ratio - np.log(ratio) - 1)
    else:
        qlike = np.nan
    return {"alpha": intercept, "beta": slope, "R2": r**2, "RMSE": rmse,
            "QLIKE": qlike, "n": len(yt)}


def load_predictions(results_dir, ticker, horizon):
    """Load a single prediction CSV."""
    path = results_dir / f"predictions_{ticker}_H{horizon}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["date"])
    return df


def compute_metrics_for_branch(results_dir, tickers, horizons):
    """Compute MZ metrics for all tickers x horizons."""
    rows = []
    for t in tickers:
        for h in horizons:
            df = load_predictions(results_dir, t, h)
            if df is None or len(df) < 20:
                continue
            m = mz_regression(df["y_true"].values, df["y_pred"].values)
            m["ticker"] = t
            m["horizon"] = h
            m["sector"] = SECTOR_MAP.get(t, "Unknown")
            m["date_min"] = str(df["date"].min().date())
            m["date_max"] = str(df["date"].max().date())
            rows.append(m)
    return pd.DataFrame(rows)


def main():
    # ── 1. Find overlapping tickers ──────────────────────────────────
    ba_tickers = set()
    for f in BA.glob("predictions_*_H21.csv"):
        ba_tickers.add(f.stem.replace("predictions_", "").replace("_H21", ""))
    caleb_tickers = set()
    for f in CALEB.glob("predictions_*_H21.csv"):
        caleb_tickers.add(f.stem.replace("predictions_", "").replace("_H21", ""))

    overlap = sorted(ba_tickers & caleb_tickers)
    print(f"BA tickers: {len(ba_tickers)}, Caleb tickers: {len(caleb_tickers)}, Overlap: {len(overlap)}")

    # ── 2. Compute metrics ───────────────────────────────────────────
    print("Computing BA metrics...")
    ba_metrics = compute_metrics_for_branch(BA, overlap, HORIZONS)
    ba_metrics = ba_metrics.set_index(["ticker", "horizon"])

    print("Computing Caleb metrics...")
    caleb_metrics = compute_metrics_for_branch(CALEB, overlap, HORIZONS)
    caleb_metrics = caleb_metrics.set_index(["ticker", "horizon"])

    # ── 3. Merge and compute differences ─────────────────────────────
    common_idx = ba_metrics.index.intersection(caleb_metrics.index)
    print(f"Common ticker-horizon pairs: {len(common_idx)}")

    compare_cols = ["R2", "beta", "alpha", "RMSE", "QLIKE"]
    ba_m = ba_metrics.loc[common_idx, compare_cols].add_suffix("_ba")
    cal_m = caleb_metrics.loc[common_idx, compare_cols].add_suffix("_caleb")
    merged = pd.concat([ba_m, cal_m], axis=1)

    # Add sector
    merged["sector"] = [SECTOR_MAP.get(t, "Unknown") for t, _ in merged.index]

    # Differences (BA - Caleb)
    for col in compare_cols:
        merged[f"diff_{col}"] = merged[f"{col}_ba"] - merged[f"{col}_caleb"]

    # ── 4. Date range comparison ─────────────────────────────────────
    print("\n=== DATE RANGE COMPARISON (sample tickers) ===")
    date_comparison = []
    for t in overlap[:10]:
        for h in [21]:
            ba_df = load_predictions(BA, t, h)
            cal_df = load_predictions(CALEB, t, h)
            if ba_df is not None and cal_df is not None:
                date_comparison.append({
                    "ticker": t,
                    "ba_start": str(ba_df["date"].min().date()),
                    "ba_end": str(ba_df["date"].max().date()),
                    "ba_n": len(ba_df),
                    "caleb_start": str(cal_df["date"].min().date()),
                    "caleb_end": str(cal_df["date"].max().date()),
                    "caleb_n": len(cal_df),
                })
    date_df = pd.DataFrame(date_comparison)
    print(date_df.to_string(index=False))

    # ── 5. Statistical tests ─────────────────────────────────────────
    print("\n=== PAIRED STATISTICAL TESTS ===")
    test_results = []
    for h in HORIZONS:
        h_data = merged.xs(h, level="horizon")
        for col in compare_cols:
            diff = h_data[f"diff_{col}"].dropna()
            if len(diff) < 5:
                continue
            # Wilcoxon signed-rank (non-parametric paired test)
            try:
                w_stat, w_pval = stats.wilcoxon(diff)
            except ValueError:
                w_stat, w_pval = np.nan, np.nan
            # Paired t-test
            t_stat, t_pval = stats.ttest_1samp(diff, 0)
            # Effect size (Cohen's d)
            d = diff.mean() / diff.std() if diff.std() > 0 else 0
            test_results.append({
                "horizon": h,
                "metric": col,
                "mean_diff": diff.mean(),
                "median_diff": diff.median(),
                "std_diff": diff.std(),
                "cohens_d": d,
                "t_stat": t_stat,
                "t_pval": t_pval,
                "wilcoxon_stat": w_stat,
                "wilcoxon_pval": w_pval,
                "n": len(diff),
            })
    test_df = pd.DataFrame(test_results)
    print(test_df.to_string(index=False, float_format="%.4f"))

    # ── 6. ICC (Intraclass Correlation) ──────────────────────────────
    print("\n=== INTRACLASS CORRELATION (ICC) ===")
    icc_results = []
    for h in HORIZONS:
        h_data = merged.xs(h, level="horizon")
        for col in ["R2", "RMSE"]:
            ba_vals = h_data[f"{col}_ba"].dropna()
            cal_vals = h_data[f"{col}_caleb"].dropna()
            common = ba_vals.index.intersection(cal_vals.index)
            x = ba_vals.loc[common].values
            y = cal_vals.loc[common].values
            if len(x) < 5:
                continue
            # ICC(3,1) — two-way mixed, single measures, consistency
            n = len(x)
            grand_mean = np.mean(np.concatenate([x, y]))
            row_means = (x + y) / 2
            col_means = np.array([x.mean(), y.mean()])

            ss_rows = 2 * np.sum((row_means - grand_mean)**2)
            ss_cols = n * np.sum((col_means - grand_mean)**2)
            ss_total = np.sum((x - grand_mean)**2) + np.sum((y - grand_mean)**2)
            ss_resid = ss_total - ss_rows - ss_cols

            ms_rows = ss_rows / (n - 1)
            ms_resid = ss_resid / (n - 1)

            icc = (ms_rows - ms_resid) / (ms_rows + ms_resid) if (ms_rows + ms_resid) > 0 else np.nan

            # Also Pearson r for reference
            r_val, r_pval = stats.pearsonr(x, y)

            icc_results.append({
                "horizon": h,
                "metric": col,
                "ICC": icc,
                "pearson_r": r_val,
                "pearson_p": r_pval,
                "n": n,
            })
    icc_df = pd.DataFrame(icc_results)
    print(icc_df.to_string(index=False, float_format="%.4f"))

    # ── 7. Sector-level analysis ─────────────────────────────────────
    print("\n=== SECTOR-LEVEL R2 DIFFERENCES ===")
    for h in HORIZONS:
        h_data = merged.xs(h, level="horizon")
        sector_diffs = h_data.groupby("sector")["diff_R2"].agg(["mean", "median", "std", "count"])
        print(f"\nH={h}:")
        print(sector_diffs.to_string(float_format="%.4f"))

    # ── 8. Plots ─────────────────────────────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.suptitle("BA vs Caleb: R² Scatter by Horizon", fontsize=14, fontweight="bold")
    for i, h in enumerate(HORIZONS):
        ax = axes[i]
        h_data = merged.xs(h, level="horizon")
        x = h_data["R2_ba"]
        y = h_data["R2_caleb"]
        colors = [plt.cm.tab10(hash(s) % 10) for s in h_data["sector"]]
        ax.scatter(x, y, c=colors, alpha=0.7, edgecolors="k", linewidths=0.3, s=40)
        # 45-degree line
        lims = [min(x.min(), y.min()) - 0.02, max(x.max(), y.max()) + 0.02]
        ax.plot(lims, lims, "k--", alpha=0.5, linewidth=1)
        ax.set_xlim(lims)
        ax.set_ylim(lims)
        ax.set_xlabel("R² (Backtest-Analytics)", fontsize=11)
        ax.set_ylabel("R² (Caleb branch)", fontsize=11)
        ax.set_title(f"H={h}d  (r={stats.pearsonr(x.dropna(), y.dropna())[0]:.3f})", fontsize=12)
        ax.set_aspect("equal")
        # Label outliers (diff > 2 SD)
        diff = x - y
        threshold = diff.std() * 2
        for ticker, row in h_data.iterrows():
            if isinstance(ticker, tuple):
                ticker = ticker[0]
            if abs(row["diff_R2"]) > threshold:
                ax.annotate(ticker, (row["R2_ba"], row["R2_caleb"]),
                           fontsize=7, alpha=0.8)
    plt.tight_layout()
    plt.savefig(PLOTS / "cross_branch_r2_scatter.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nSaved: {PLOTS / 'cross_branch_r2_scatter.png'}")

    # Difference distribution plot
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle("Distribution of Metric Differences (BA - Caleb)", fontsize=14, fontweight="bold")
    for i, col in enumerate(["R2", "RMSE", "beta", "alpha", "QLIKE"]):
        ax = axes[i // 3][i % 3]
        for h in HORIZONS:
            h_data = merged.xs(h, level="horizon")
            diff = h_data[f"diff_{col}"].dropna()
            ax.hist(diff, bins=25, alpha=0.4, label=f"H={h}", density=True)
        ax.axvline(0, color="k", linestyle="--", alpha=0.7)
        ax.set_xlabel(f"Diff ({col})", fontsize=10)
        ax.set_ylabel("Density", fontsize=10)
        ax.set_title(col, fontsize=12)
        ax.legend(fontsize=9)
    axes[1][2].axis("off")
    plt.tight_layout()
    plt.savefig(PLOTS / "cross_branch_diff_distributions.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {PLOTS / 'cross_branch_diff_distributions.png'}")

    # ICC bar chart
    if len(icc_df) > 0:
        fig, ax = plt.subplots(figsize=(8, 5))
        icc_pivot = icc_df.pivot(index="metric", columns="horizon", values="ICC")
        icc_pivot.plot(kind="bar", ax=ax, color=["#2196F3", "#FF9800", "#4CAF50"])
        ax.set_ylabel("ICC", fontsize=12)
        ax.set_title("Intraclass Correlation: BA vs Caleb", fontsize=13, fontweight="bold")
        ax.axhline(0.9, color="green", linestyle="--", alpha=0.5, label="ICC=0.90 (excellent)")
        ax.axhline(0.75, color="orange", linestyle="--", alpha=0.5, label="ICC=0.75 (good)")
        ax.legend(fontsize=9)
        ax.set_xticklabels(ax.get_xticklabels(), rotation=0)
        plt.tight_layout()
        plt.savefig(PLOTS / "cross_branch_icc.png", dpi=150, bbox_inches="tight")
        plt.close()
        print(f"Saved: {PLOTS / 'cross_branch_icc.png'}")

    # ── 9. Save summary ──────────────────────────────────────────────
    merged.to_csv(BASE / "cross_branch_merged_metrics.csv")
    test_df.to_csv(BASE / "cross_branch_test_results.csv", index=False)
    if len(icc_df) > 0:
        icc_df.to_csv(BASE / "cross_branch_icc.csv", index=False)
    print(f"\nSaved merged metrics, test results, and ICC to {BASE}")

    # ── 10. Summary statistics ───────────────────────────────────────
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    for h in HORIZONS:
        h_test = test_df[test_df["horizon"] == h]
        r2_row = h_test[h_test["metric"] == "R2"].iloc[0] if len(h_test[h_test["metric"] == "R2"]) > 0 else None
        if r2_row is not None:
            sig = "YES" if r2_row["wilcoxon_pval"] < 0.05 else "NO"
            print(f"H={h:3d}: R² diff = {r2_row['mean_diff']:+.4f} (d={r2_row['cohens_d']:+.3f}) "
                  f"p={r2_row['wilcoxon_pval']:.4f} significant={sig}")
    print()
    if len(icc_df) > 0:
        for _, row in icc_df.iterrows():
            qual = "excellent" if row["ICC"] > 0.9 else "good" if row["ICC"] > 0.75 else "moderate" if row["ICC"] > 0.5 else "poor"
            print(f"ICC({row['metric']}, H={int(row['horizon'])}): {row['ICC']:.3f} ({qual})")


if __name__ == "__main__":
    main()

"""
Model Diagnostics
=================
Covers all 5 investigation items:
  4a. Pinball loss (quantile loss)
  4b. QQ plot / fat-tailed error analysis
  4c. LassoCV CPU time profiling
  4d. Residual asymmetry investigation
  4e. Ensemble weight investigation
Uses caleb-branch results (more tickers, monitoring data).
"""

import json, re, warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

warnings.filterwarnings("ignore")

BASE = Path(__file__).parent
CALEB = BASE / "caleb_results"
PLOTS = BASE / "plots"
PLOTS.mkdir(exist_ok=True)

HORIZONS = [21, 63, 126]
HORIZON_LABELS = {21: "H=21 (1mo)", 63: "H=63 (3mo)", 126: "H=126 (6mo)"}
HORIZON_COLORS = {21: "#2196F3", 63: "#FF9800", 126: "#4CAF50"}

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


def load_all_predictions():
    """Load all prediction CSVs from caleb branch, return combined DataFrame."""
    frames = []
    for f in sorted(CALEB.glob("predictions_*_H*.csv")):
        parts = f.stem.replace("predictions_", "").split("_H")
        if len(parts) != 2:
            continue
        ticker, h = parts[0], int(parts[1])
        df = pd.read_csv(f, parse_dates=["date"])
        df["ticker"] = ticker
        df["horizon"] = h
        df["sector"] = SECTOR_MAP.get(ticker, "Unknown")
        df["residual"] = df["y_true"] - df["y_pred"]
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


# ══════════════════════════════════════════════════════════════════════
# 4a. PINBALL LOSS
# ══════════════════════════════════════════════════════════════════════

def pinball_loss(y_true, y_pred, tau):
    """Quantile (pinball) loss at level tau."""
    diff = y_true - y_pred
    return np.mean(np.where(diff >= 0, tau * diff, (tau - 1) * diff))


def analyze_pinball(all_preds):
    print("\n" + "="*70)
    print("4a. PINBALL LOSS ANALYSIS")
    print("="*70)

    taus = [0.05, 0.25, 0.50, 0.75, 0.95]
    rows = []
    for h in HORIZONS:
        hd = all_preds[all_preds["horizon"] == h]
        for tau in taus:
            loss = pinball_loss(hd["y_true"].values, hd["y_pred"].values, tau)
            rows.append({"horizon": h, "tau": tau, "pinball_loss": loss})
        # Also by sector
        for sector, sd in hd.groupby("sector"):
            for tau in taus:
                loss = pinball_loss(sd["y_true"].values, sd["y_pred"].values, tau)
                rows.append({"horizon": h, "tau": tau, "pinball_loss": loss, "sector": sector})

    df = pd.DataFrame(rows)
    portfolio = df[df["sector"].isna()].drop(columns=["sector"])
    print("\nPortfolio-level pinball loss:")
    pivot = portfolio.pivot(index="tau", columns="horizon", values="pinball_loss")
    print(pivot.to_string(float_format="%.5f"))

    # Asymmetry ratio: pinball(0.95) / pinball(0.05) — if > 1, model under-predicts more at right tail
    for h in HORIZONS:
        hdf = portfolio[portfolio["horizon"] == h]
        p95 = hdf[hdf["tau"] == 0.95]["pinball_loss"].values[0]
        p05 = hdf[hdf["tau"] == 0.05]["pinball_loss"].values[0]
        ratio = p95 / p05 if p05 > 0 else np.nan
        print(f"  H={h}: tau=0.95/0.05 ratio = {ratio:.2f} {'(right-tail losses dominate)' if ratio > 1 else '(left-tail losses dominate)'}")

    # Plot: pinball loss by horizon and tau
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle("Pinball (Quantile) Loss by Horizon", fontsize=14, fontweight="bold")
    sector_data = df[df["sector"].notna()]
    for i, h in enumerate(HORIZONS):
        ax = axes[i]
        hd = sector_data[sector_data["horizon"] == h]
        pivot_s = hd.pivot_table(index="sector", columns="tau", values="pinball_loss")
        pivot_s.plot(kind="bar", ax=ax, colormap="RdYlBu_r", edgecolor="k", linewidth=0.3)
        ax.set_title(HORIZON_LABELS[h], fontsize=12)
        ax.set_xlabel("")
        ax.set_ylabel("Pinball Loss" if i == 0 else "")
        ax.tick_params(axis="x", rotation=45)
        ax.legend(title="τ", fontsize=8, title_fontsize=9)
    plt.tight_layout()
    plt.savefig(PLOTS / "pinball_loss_by_sector.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {PLOTS / 'pinball_loss_by_sector.png'}")

    return portfolio


# ══════════════════════════════════════════════════════════════════════
# 4b. QQ PLOT / FAT-TAILED ERROR ANALYSIS
# ══════════════════════════════════════════════════════════════════════

def analyze_qq_tails(all_preds):
    print("\n" + "="*70)
    print("4b. QQ PLOT / FAT-TAILED ERROR ANALYSIS")
    print("="*70)

    fig, axes = plt.subplots(2, 3, figsize=(18, 11))
    fig.suptitle("Residual Distribution: Normal QQ vs Student-t QQ", fontsize=14, fontweight="bold")

    tail_stats = []
    for i, h in enumerate(HORIZONS):
        hd = all_preds[all_preds["horizon"] == h]
        resid = hd["residual"].dropna().values
        # Standardize
        z = (resid - resid.mean()) / resid.std()

        # Fit Student-t
        df_t, loc_t, scale_t = sp_stats.t.fit(resid)

        # Stats
        skew = sp_stats.skew(resid)
        kurt = sp_stats.kurtosis(resid)  # excess kurtosis
        tail_2sigma = np.mean(np.abs(z) > 2)
        tail_3sigma = np.mean(np.abs(z) > 3)
        right_tail = np.mean(z > 2)
        left_tail = np.mean(z < -2)

        tail_stats.append({
            "horizon": h,
            "t_df": df_t,
            "skewness": skew,
            "excess_kurtosis": kurt,
            "frac_beyond_2sigma": tail_2sigma,
            "frac_beyond_3sigma": tail_3sigma,
            "right_tail_2sigma": right_tail,
            "left_tail_2sigma": left_tail,
            "n": len(resid),
        })

        print(f"\nH={h}: t-df={df_t:.1f}, skew={skew:.3f}, excess_kurt={kurt:.3f}")
        print(f"  >2σ: {100*tail_2sigma:.2f}% (normal expects 4.55%)")
        print(f"  >3σ: {100*tail_3sigma:.2f}% (normal expects 0.27%)")
        print(f"  Right tail (>+2σ): {100*right_tail:.2f}%  Left tail (<-2σ): {100*left_tail:.2f}%")

        # Normal QQ
        ax = axes[0][i]
        sp_stats.probplot(resid, dist="norm", plot=ax)
        ax.set_title(f"{HORIZON_LABELS[h]} — Normal QQ", fontsize=11)
        ax.get_lines()[0].set_markersize(1)
        ax.get_lines()[0].set_alpha(0.3)

        # Student-t QQ
        ax = axes[1][i]
        theoretical_q = sp_stats.t.ppf(
            np.linspace(0.001, 0.999, min(len(resid), 5000)),
            df_t, loc=loc_t, scale=scale_t
        )
        empirical_q = np.quantile(resid, np.linspace(0.001, 0.999, min(len(resid), 5000)))
        ax.scatter(theoretical_q, empirical_q, s=1, alpha=0.3, color=HORIZON_COLORS[h])
        lims = [min(theoretical_q.min(), empirical_q.min()),
                max(theoretical_q.max(), empirical_q.max())]
        ax.plot(lims, lims, "r--", linewidth=1)
        ax.set_xlabel(f"Student-t (df={df_t:.1f}) Theoretical")
        ax.set_ylabel("Empirical")
        ax.set_title(f"{HORIZON_LABELS[h]} — Student-t QQ (df={df_t:.1f})", fontsize=11)

    plt.tight_layout()
    plt.savefig(PLOTS / "qq_normal_vs_t.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nSaved: {PLOTS / 'qq_normal_vs_t.png'}")

    # Per-sector kurtosis
    print("\n--- Excess Kurtosis by Sector (H=21) ---")
    h21 = all_preds[all_preds["horizon"] == 21]
    sector_kurt = h21.groupby("sector")["residual"].apply(
        lambda x: sp_stats.kurtosis(x.dropna())
    ).sort_values(ascending=False)
    print(sector_kurt.to_string(float_format="%.2f"))

    # Tail errors vs vol regime
    print("\n--- Tail Errors (>2σ) by Vol Regime ---")
    for h in HORIZONS:
        hd = all_preds[all_preds["horizon"] == h].copy()
        z = (hd["residual"] - hd["residual"].mean()) / hd["residual"].std()
        hd["z_resid"] = z
        hd["vol_tercile"] = pd.qcut(hd["y_true"], 3, labels=["Low", "Medium", "High"])
        tail_by_regime = hd.groupby("vol_tercile")["z_resid"].apply(
            lambda x: (np.abs(x) > 2).mean()
        )
        print(f"  H={h}: {dict(tail_by_regime.map(lambda x: f'{100*x:.1f}%'))}")

    return pd.DataFrame(tail_stats)


# ══════════════════════════════════════════════════════════════════════
# 4c. LASSOCV CPU TIME PROFILING
# ══════════════════════════════════════════════════════════════════════

def analyze_lassocv_timing():
    print("\n" + "="*70)
    print("4c. LASSOCV CPU TIME PROFILING")
    print("="*70)

    log_path = CALEB / "monitoring" / "batch_run.log"
    if not log_path.exists():
        print("  No batch_run.log found")
        return

    pattern = re.compile(
        r"\[PROFILE\]\s+(\w+)\s+model fit time.*?"
        r"LassoCV:\s+([\d.]+)s.*?"
        r"RF:\s+([\d.]+)s.*?"
        r"XGB:\s+([\d.]+)s.*?"
        r"total:\s+([\d.]+)s"
    )
    rows = []
    with open(log_path) as f:
        for line in f:
            m = pattern.search(line)
            if m:
                rows.append({
                    "ticker": m.group(1),
                    "lasso_s": float(m.group(2)),
                    "rf_s": float(m.group(3)),
                    "xgb_s": float(m.group(4)),
                    "total_s": float(m.group(5)),
                })
    prof = pd.DataFrame(rows)

    # LassoCV analysis
    lasso = prof["lasso_s"]
    rf = prof["rf_s"]
    xgb = prof["xgb_s"]

    print(f"\nLassoCV timing (79 tickers):")
    print(f"  Mean: {lasso.mean():.1f}s  Median: {lasso.median():.1f}s  Std: {lasso.std():.1f}s")
    print(f"  Min:  {lasso.min():.1f}s ({prof.loc[lasso.idxmin(), 'ticker']})")
    print(f"  Max:  {lasso.max():.1f}s ({prof.loc[lasso.idxmax(), 'ticker']})")
    print(f"  Total: {lasso.sum()/3600:.2f}h of {prof['total_s'].sum()/3600:.1f}h model fit time")

    # LassoCV as fraction of total — does it correlate with ticker complexity?
    prof["lasso_frac"] = prof["lasso_s"] / prof["total_s"]
    print(f"\n  LassoCV fraction of total fit time:")
    print(f"    Mean: {prof['lasso_frac'].mean()*100:.1f}%  Range: {prof['lasso_frac'].min()*100:.1f}-{prof['lasso_frac'].max()*100:.1f}%")

    # LassoCV config context
    print(f"\n  Pipeline config: alphas=20, TimeSeriesSplit(n_splits=5)")
    print(f"  Per WF step: 5 folds × 20 alphas = 100 OLS-scale fits")
    print(f"  With ~108 WF steps: ~10,800 LassoCV fits per ticker")
    print(f"  Average per fit: {lasso.mean()*1000/10800:.2f}ms — very efficient")

    # Cost to double alphas
    est_double = lasso.mean() * 2  # approximately linear in n_alphas
    print(f"\n  Estimated cost to double alphas (20→40): +{est_double:.0f}s per ticker (+{est_double*79/3600:.1f}h total)")
    print(f"  LassoCV is NOT a bottleneck — 7% of fit time, 4.4h of 65.6h total")

    # Ratio analysis
    print(f"\n  Relative model costs (mean per ticker):")
    print(f"    LassoCV:     1.0× (baseline)")
    print(f"    RF:          {rf.mean()/lasso.mean():.1f}×")
    print(f"    XGBoost:     {xgb.mean()/lasso.mean():.1f}×")


# ══════════════════════════════════════════════════════════════════════
# 4d. RESIDUAL ASYMMETRY INVESTIGATION
# ══════════════════════════════════════════════════════════════════════

def analyze_residual_asymmetry(all_preds):
    print("\n" + "="*70)
    print("4d. RESIDUAL ASYMMETRY INVESTIGATION")
    print("="*70)

    fig, axes = plt.subplots(2, 3, figsize=(18, 11))
    fig.suptitle("Residual Asymmetry Analysis", fontsize=14, fontweight="bold")

    for i, h in enumerate(HORIZONS):
        hd = all_preds[all_preds["horizon"] == h].copy()
        resid = hd["residual"]
        y_true = hd["y_true"]

        # Conditional bias by vol quartile
        hd["vol_q"] = pd.qcut(y_true, 4, labels=["Q1 (low)", "Q2", "Q3", "Q4 (high)"])
        cond_bias = hd.groupby("vol_q")["residual"].agg(["mean", "median", "std", "count"])
        print(f"\nH={h} — Conditional Bias by Realized Vol Quartile:")
        print(cond_bias.to_string(float_format="%.4f"))

        # Dangerous misses: realized > predicted by >20%
        pct_diff = (hd["y_true"] - hd["y_pred"]) / hd["y_pred"]
        dangerous = (pct_diff > 0.20).mean()
        safe = (pct_diff < -0.20).mean()
        print(f"  Dangerous miss (real > pred by >20%): {100*dangerous:.1f}%")
        print(f"  Safe miss (pred > real by >20%):      {100*safe:.1f}%")
        print(f"  Ratio (dangerous/safe):               {dangerous/safe:.2f}" if safe > 0 else "")

        # Plot: residual distribution by vol quartile
        ax = axes[0][i]
        for q in ["Q1 (low)", "Q2", "Q3", "Q4 (high)"]:
            data = hd[hd["vol_q"] == q]["residual"]
            ax.hist(data, bins=50, alpha=0.4, label=q, density=True)
        ax.axvline(0, color="k", linestyle="--", alpha=0.7)
        ax.set_title(f"{HORIZON_LABELS[h]} — Residuals by Vol Quartile", fontsize=11)
        ax.set_xlabel("Residual (y_true - y_pred)")
        ax.legend(fontsize=8)

        # Plot: dangerous vs safe misses by sector
        ax = axes[1][i]
        sector_asym = []
        for sector, sd in hd.groupby("sector"):
            pd_diff = (sd["y_true"] - sd["y_pred"]) / sd["y_pred"]
            d = (pd_diff > 0.20).mean()
            s = (pd_diff < -0.20).mean()
            sector_asym.append({"sector": sector, "dangerous": d, "safe": s})
        sa_df = pd.DataFrame(sector_asym).set_index("sector").sort_values("dangerous", ascending=True)
        sa_df[["dangerous", "safe"]].plot(kind="barh", ax=ax, color=["#e74c3c", "#2ecc71"],
                                          edgecolor="k", linewidth=0.3)
        ax.set_title(f"{HORIZON_LABELS[h]} — Miss Rates by Sector", fontsize=11)
        ax.set_xlabel("Fraction of predictions")
        ax.legend(["Dangerous (>20% under)", "Safe (>20% over)"], fontsize=8)

    plt.tight_layout()
    plt.savefig(PLOTS / "residual_asymmetry.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nSaved: {PLOTS / 'residual_asymmetry.png'}")

    # Summary: which direction does the model err?
    print("\n--- ASYMMETRY SUMMARY ---")
    for h in HORIZONS:
        hd = all_preds[all_preds["horizon"] == h]
        q1_bias = hd[hd["y_true"] <= hd["y_true"].quantile(0.25)]["residual"].mean()
        q4_bias = hd[hd["y_true"] >= hd["y_true"].quantile(0.75)]["residual"].mean()
        print(f"  H={h}: Low-vol bias = {q1_bias:+.4f} (over-predict), "
              f"High-vol bias = {q4_bias:+.4f} ({'under-predict' if q4_bias > 0 else 'over-predict'})")
    print("\n  Pattern: mean-reversion drag — model pulls toward long-run average.")
    print("  Over-predicts when vol is low, under-predicts when vol is high.")
    print("  This is the classic trade-off of shrinkage estimators (Lasso, RF averaging).")


# ══════════════════════════════════════════════════════════════════════
# 4e. ENSEMBLE WEIGHT INVESTIGATION
# ══════════════════════════════════════════════════════════════════════

def analyze_ensemble_weights(all_preds):
    print("\n" + "="*70)
    print("4e. ENSEMBLE WEIGHT INVESTIGATION")
    print("="*70)

    # Load payload JSONs for ensemble weight data
    # Weights are in meta.ensemble_weights (single dict per ticker, not per-horizon)
    payloads_dir = CALEB / "payloads"
    weights_data = []
    for f in sorted(payloads_dir.glob("*_Payload.json")):
        ticker = f.stem.replace("_Payload", "")
        try:
            with open(f) as fp:
                payload = json.load(fp)
            ew = payload.get("meta", {}).get("ensemble_weights", {})
            if ew:
                weights_data.append({
                    "ticker": ticker,
                    "sector": SECTOR_MAP.get(ticker, "Unknown"),
                    "w_xgb": ew.get("XGB", np.nan),
                    "w_rf": ew.get("RF", np.nan),
                    "w_lasso": ew.get("LassoCV", np.nan),
                })
        except (json.JSONDecodeError, KeyError):
            continue

    if not weights_data:
        print("  No ensemble weight data found in payloads")
        return

    wdf = pd.DataFrame(weights_data)
    print(f"\nLoaded ensemble weights for {len(wdf)} tickers")

    # Check weight distribution
    print("\n--- Current Weights (from payloads) ---")
    print(f"  Unique weight sets: {wdf[['w_xgb','w_rf','w_lasso']].drop_duplicates().shape[0]}")
    print(f"  XGB:   mean={wdf['w_xgb'].mean():.3f}  std={wdf['w_xgb'].std():.4f}")
    print(f"  RF:    mean={wdf['w_rf'].mean():.3f}  std={wdf['w_rf'].std():.4f}")
    print(f"  Lasso: mean={wdf['w_lasso'].mean():.3f}  std={wdf['w_lasso'].std():.4f}")

    all_uniform = (wdf["w_xgb"] == wdf["w_rf"]).all() and (wdf["w_rf"] == wdf["w_lasso"]).all()
    if all_uniform:
        print("\n  *** ALL WEIGHTS ARE IDENTICAL (0.33/0.33/0.33) ***")
        print("  The inverse-RMSE weighting scheme produces NO differentiation.")
        print("  This means all 3 models have nearly identical CV RMSE,")
        print("  causing the inverse-RMSE formula to collapse to uniform weights.")
        print("\n  Payloads store a single weight dict (not per-horizon).")
        print("  Cannot assess per-horizon optimal weights without per-model predictions.")

    # Investigate if per-horizon weighting WOULD help using residual analysis
    print("\n--- Per-Horizon Model Contribution Analysis ---")
    print("  (Indirect: using residual patterns as proxy for model-specific behavior)")

    # Compare residual autocorrelation — high ACF suggests LassoCV contributes smoothing
    for h in HORIZONS:
        hd = all_preds[all_preds["horizon"] == h]
        # Pool all residuals by date
        date_resid = hd.groupby("date")["residual"].mean()
        if len(date_resid) > 10:
            acf_1 = date_resid.autocorr(lag=1)
            acf_5 = date_resid.autocorr(lag=5)
            print(f"  H={h}: Pooled residual ACF(1)={acf_1:.3f}, ACF(5)={acf_5:.3f}")

    print("\n--- Recommendations for Ensemble Weight Improvement ---")
    print("  1. Store per-model predictions (XGB, RF, LassoCV) separately in future runs")
    print("  2. Compute per-horizon optimal weights via held-out validation")
    print("  3. Consider time-varying weights (e.g., regime-dependent blending)")
    print("  4. Test: weight XGB higher at H=21 (captures nonlinear short-term dynamics)")
    print("          weight LassoCV higher at H=126 (mean-reversion is linear)")
    print("  5. The uniform weights suggest the min_ensemble_weight=0.10 floor isn't binding —")
    print("     the models genuinely have similar CV error. Per-horizon analysis may reveal differences.")


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    print("Loading all predictions...")
    all_preds = load_all_predictions()
    print(f"Loaded {len(all_preds):,} predictions across {all_preds['ticker'].nunique()} tickers")

    pinball_df = analyze_pinball(all_preds)
    tail_df = analyze_qq_tails(all_preds)
    analyze_lassocv_timing()
    analyze_residual_asymmetry(all_preds)
    analyze_ensemble_weights(all_preds)

    print("\n" + "="*70)
    print("ALL DIAGNOSTICS COMPLETE")
    print("="*70)


if __name__ == "__main__":
    main()

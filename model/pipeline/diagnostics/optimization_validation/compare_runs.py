"""
Validate optimized pipeline run against standard run.

Compares per-date predictions for AAPL and MSFT at H=21 between
results/ (standard CPU pipeline) and results_optimized/ (GPU XGBoost,
ProcessPoolExecutor, LassoCV n_jobs=-1, vectorized inference).

Acceptance tier: calibration + ranking preserved.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import LinearRegression


HERE = Path(__file__).resolve().parent
PIPELINE = HERE.parent.parent
STD_DIR = PIPELINE / "results"
OPT_DIR = PIPELINE / "results_optimized"
PLOTS_DIR = HERE / "plots"

TICKERS = ["AAPL", "MSFT"]
HORIZON = 21

# Acceptance thresholds
RMSE_REL_TOL = 0.02
QLIKE_REL_TOL = 0.02
DBETA_TOL = 0.02
DALPHA_TOL = 0.01
DR2_TOL = 0.01
SPEARMAN_MIN = 0.98
EVENT_JACCARD_MIN = 0.95
INPUT_EQUAL_TOL = 1e-10


def load_and_join(ticker: str) -> pd.DataFrame:
    std_path = STD_DIR / f"predictions_{ticker}_H{HORIZON}.csv"
    opt_path = OPT_DIR / f"predictions_{ticker}_H{HORIZON}.csv"
    std = pd.read_csv(std_path, parse_dates=["date"])
    opt = pd.read_csv(opt_path, parse_dates=["date"])
    joined = std.merge(opt, on="date", how="inner", suffixes=("_std", "_opt"))
    joined = joined.sort_values("date").reset_index(drop=True)
    return joined


def check_inputs_identical(df: pd.DataFrame, ticker: str) -> List[str]:
    """Return list of input columns that differ beyond tolerance."""
    failures = []
    for col in ["y_true", "vrp_wedge", "put_call_skew_30d"]:
        a = df[f"{col}_std"].values
        b = df[f"{col}_opt"].values
        max_abs = float(np.max(np.abs(a - b)))
        if max_abs > INPUT_EQUAL_TOL:
            failures.append(f"{ticker}:{col} max_abs_diff={max_abs:.3e}")
    return failures


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    y_true = np.clip(y_true, 1e-6, None)
    y_pred = np.clip(y_pred, 1e-6, None)
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    lr = LinearRegression().fit(y_pred.reshape(-1, 1), y_true)
    mz_alpha = float(lr.intercept_)
    mz_beta = float(lr.coef_[0])
    mz_r2 = float(lr.score(y_pred.reshape(-1, 1), y_true))
    ratio = y_true / y_pred
    qlike = float(np.mean(ratio - np.log(ratio) - 1))
    return {
        "rmse": rmse,
        "mz_alpha": mz_alpha,
        "mz_beta": mz_beta,
        "mz_r2": mz_r2,
        "qlike": qlike,
    }


def event_flags(y_pred: np.ndarray) -> np.ndarray:
    thresh = y_pred.mean() + 2.0 * y_pred.std()
    return y_pred > thresh


def jaccard(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(bool)
    b = b.astype(bool)
    inter = int(np.sum(a & b))
    union = int(np.sum(a | b))
    if union == 0:
        return 1.0
    return inter / union


def make_plots(ticker: str, df: pd.DataFrame) -> None:
    dates = df["date"]
    y_true = df["y_true_std"].values
    y_std = df["y_pred_std"].values
    y_opt = df["y_pred_opt"].values

    # Scatter y_pred_std vs y_pred_opt
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(y_std, y_opt, s=4, alpha=0.4)
    lo = float(min(y_std.min(), y_opt.min()))
    hi = float(max(y_std.max(), y_opt.max()))
    ax.plot([lo, hi], [lo, hi], color="red", linewidth=1, label="y=x")
    ax.set_xlabel("y_pred standard")
    ax.set_ylabel("y_pred optimized")
    ax.set_title(f"{ticker} H{HORIZON}: y_pred standard vs optimized")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / f"scatter_ypred_{ticker}.png", dpi=120)
    plt.close(fig)

    # Residual histograms
    res_std = y_true - y_std
    res_opt = y_true - y_opt
    fig, ax = plt.subplots(figsize=(7, 4))
    bins = np.linspace(
        min(res_std.min(), res_opt.min()),
        max(res_std.max(), res_opt.max()),
        60,
    )
    ax.hist(res_std, bins=bins, alpha=0.5, label="standard")
    ax.hist(res_opt, bins=bins, alpha=0.5, label="optimized")
    ax.set_xlabel("residual (y_true - y_pred)")
    ax.set_ylabel("count")
    ax.set_title(f"{ticker} H{HORIZON}: residual distribution")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / f"residual_hist_{ticker}.png", dpi=120)
    plt.close(fig)

    # Rolling RMSE (60d)
    window = 60
    rmse_std = pd.Series((y_true - y_std) ** 2).rolling(window).mean().pow(0.5)
    rmse_opt = pd.Series((y_true - y_opt) ** 2).rolling(window).mean().pow(0.5)
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(dates, rmse_std, label="standard", linewidth=1)
    ax.plot(dates, rmse_opt, label="optimized", linewidth=1)
    ax.set_xlabel("date")
    ax.set_ylabel(f"{window}d rolling RMSE")
    ax.set_title(f"{ticker} H{HORIZON}: rolling RMSE")
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / f"rolling_rmse_{ticker}.png", dpi=120)
    plt.close(fig)

    # Diff over time with 2σ bands
    diff = y_opt - y_std
    mu = diff.mean()
    sd = diff.std()
    outlier = np.abs(diff - mu) > 2 * sd
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(dates, diff, linewidth=0.7, label="y_pred_opt - y_pred_std")
    ax.axhline(mu + 2 * sd, color="red", linestyle="--", linewidth=0.8, label="±2σ")
    ax.axhline(mu - 2 * sd, color="red", linestyle="--", linewidth=0.8)
    ax.scatter(dates[outlier], diff[outlier], color="red", s=6, label="|Δ|>2σ")
    ax.set_xlabel("date")
    ax.set_ylabel("Δy_pred")
    ax.set_title(f"{ticker} H{HORIZON}: prediction drift over time")
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / f"diff_over_time_{ticker}.png", dpi=120)
    plt.close(fig)


def evaluate_ticker(ticker: str) -> Tuple[Dict, pd.DataFrame, List[str]]:
    joined = load_and_join(ticker)
    n = len(joined)

    input_failures = check_inputs_identical(joined, ticker)

    y_true = joined["y_true_std"].values
    y_std = joined["y_pred_std"].values
    y_opt = joined["y_pred_opt"].values

    m_std = compute_metrics(y_true, y_std)
    m_opt = compute_metrics(y_true, y_opt)

    rmse_rel = (m_opt["rmse"] - m_std["rmse"]) / m_std["rmse"]
    qlike_rel = (m_opt["qlike"] - m_std["qlike"]) / m_std["qlike"]

    pearson = float(stats.pearsonr(y_std, y_opt).statistic)
    spearman = float(stats.spearmanr(y_std, y_opt).statistic)

    res_std = y_true - y_std
    res_opt = y_true - y_opt
    ks = stats.ks_2samp(res_std, res_opt)
    ks_p = float(ks.pvalue)

    flags_std = event_flags(y_std)
    flags_opt = event_flags(y_opt)
    event_j = jaccard(flags_std, flags_opt)

    # Per-component correlations (optimized only)
    comp_corr = {}
    for comp in ["pred_XGB", "pred_RF", "pred_LassoCV"]:
        if comp in joined.columns:
            comp_corr[comp] = float(
                stats.pearsonr(joined[comp].values, y_std).statistic
            )

    # Acceptance checks
    failures: List[str] = list(input_failures)
    if abs(rmse_rel) > RMSE_REL_TOL:
        failures.append(f"RMSE relative delta {rmse_rel:+.4f} exceeds ±{RMSE_REL_TOL}")
    if abs(qlike_rel) > QLIKE_REL_TOL:
        failures.append(f"QLIKE relative delta {qlike_rel:+.4f} exceeds ±{QLIKE_REL_TOL}")
    if abs(m_opt["mz_beta"] - m_std["mz_beta"]) > DBETA_TOL:
        failures.append(
            f"|Δβ|={abs(m_opt['mz_beta'] - m_std['mz_beta']):.4f} exceeds {DBETA_TOL}"
        )
    if abs(m_opt["mz_alpha"] - m_std["mz_alpha"]) > DALPHA_TOL:
        failures.append(
            f"|Δα|={abs(m_opt['mz_alpha'] - m_std['mz_alpha']):.4f} exceeds {DALPHA_TOL}"
        )
    if abs(m_opt["mz_r2"] - m_std["mz_r2"]) > DR2_TOL:
        failures.append(
            f"|ΔR²|={abs(m_opt['mz_r2'] - m_std['mz_r2']):.4f} exceeds {DR2_TOL}"
        )
    if spearman < SPEARMAN_MIN:
        failures.append(f"Spearman={spearman:.4f} below {SPEARMAN_MIN}")
    if event_j < EVENT_JACCARD_MIN:
        failures.append(f"Event Jaccard={event_j:.4f} below {EVENT_JACCARD_MIN}")

    diff = y_opt - y_std
    pointwise = pd.DataFrame({
        "ticker": ticker,
        "date": joined["date"],
        "y_true": y_true,
        "y_pred_std": y_std,
        "y_pred_opt": y_opt,
        "diff": diff,
        "res_std": res_std,
        "res_opt": res_opt,
    })

    summary = {
        "ticker": ticker,
        "n": n,
        "rmse_std": m_std["rmse"],
        "rmse_opt": m_opt["rmse"],
        "rmse_rel_delta": rmse_rel,
        "mz_alpha_std": m_std["mz_alpha"],
        "mz_alpha_opt": m_opt["mz_alpha"],
        "mz_beta_std": m_std["mz_beta"],
        "mz_beta_opt": m_opt["mz_beta"],
        "mz_r2_std": m_std["mz_r2"],
        "mz_r2_opt": m_opt["mz_r2"],
        "qlike_std": m_std["qlike"],
        "qlike_opt": m_opt["qlike"],
        "qlike_rel_delta": qlike_rel,
        "pearson_ypred": pearson,
        "spearman_ypred": spearman,
        "event_jaccard": event_j,
        "ks_pvalue": ks_p,
        "diff_mean": float(diff.mean()),
        "diff_std": float(diff.std()),
        "diff_max_abs": float(np.max(np.abs(diff))),
        "diff_mean_abs": float(np.mean(np.abs(diff))),
        "diff_median_abs": float(np.median(np.abs(diff))),
        "corr_xgb_vs_std": comp_corr.get("pred_XGB"),
        "corr_rf_vs_std": comp_corr.get("pred_RF"),
        "corr_lasso_vs_std": comp_corr.get("pred_LassoCV"),
        "pass_flag": len(failures) == 0,
    }

    make_plots(ticker, joined)

    return summary, pointwise, failures


def write_report(
    summaries: List[Dict], failures_by_ticker: Dict[str, List[str]]
) -> None:
    lines: List[str] = []
    lines.append("# Optimized vs Standard Pipeline — Comparison Report")
    lines.append("")
    lines.append(f"Horizon: H={HORIZON}  |  Tickers: {', '.join(TICKERS)}")
    lines.append("")
    lines.append("## Acceptance tier: calibration + ranking preserved")
    lines.append("")
    lines.append(
        "- RMSE / QLIKE relative delta within ±2%"
        "  |  |Δβ|<0.02, |Δα|<0.01, |ΔR²|<0.01"
        "  |  Spearman(y_pred) > 0.98"
        "  |  Event-flag Jaccard > 0.95"
    )
    lines.append("")

    for s in summaries:
        t = s["ticker"]
        verdict = "PASS" if s["pass_flag"] else "FAIL"
        lines.append(f"## {t} (n={s['n']}) — VERDICT: {verdict}")
        lines.append("")
        lines.append(
            f"- RMSE: std={s['rmse_std']:.5f}  opt={s['rmse_opt']:.5f}  "
            f"rel_delta={s['rmse_rel_delta']:+.4%}"
        )
        lines.append(
            f"- QLIKE: std={s['qlike_std']:.5f}  opt={s['qlike_opt']:.5f}  "
            f"rel_delta={s['qlike_rel_delta']:+.4%}"
        )
        lines.append(
            f"- MZ α: std={s['mz_alpha_std']:+.5f}  opt={s['mz_alpha_opt']:+.5f}  "
            f"Δ={s['mz_alpha_opt'] - s['mz_alpha_std']:+.5f}"
        )
        lines.append(
            f"- MZ β: std={s['mz_beta_std']:.5f}  opt={s['mz_beta_opt']:.5f}  "
            f"Δ={s['mz_beta_opt'] - s['mz_beta_std']:+.5f}"
        )
        lines.append(
            f"- MZ R²: std={s['mz_r2_std']:.5f}  opt={s['mz_r2_opt']:.5f}  "
            f"Δ={s['mz_r2_opt'] - s['mz_r2_std']:+.5f}"
        )
        lines.append(
            f"- Pearson(y_pred): {s['pearson_ypred']:.5f}  |  "
            f"Spearman(y_pred): {s['spearman_ypred']:.5f}"
        )
        lines.append(f"- Event-flag Jaccard: {s['event_jaccard']:.4f}")
        lines.append(
            f"- KS p-value (residuals): {s['ks_pvalue']:.4f}"
        )
        lines.append(
            f"- Δy_pred: mean={s['diff_mean']:+.5f}  std={s['diff_std']:.5f}  "
            f"max|Δ|={s['diff_max_abs']:.5f}  mean|Δ|={s['diff_mean_abs']:.5f}"
        )
        if s["corr_xgb_vs_std"] is not None:
            lines.append(
                "- Optimized components vs standard y_pred (Pearson):  "
                f"XGB={s['corr_xgb_vs_std']:.4f}  "
                f"RF={s['corr_rf_vs_std']:.4f}  "
                f"LassoCV={s['corr_lasso_vs_std']:.4f}"
            )
        if failures_by_ticker.get(t):
            lines.append("")
            lines.append("**Failures:**")
            for f in failures_by_ticker[t]:
                lines.append(f"  - {f}")
        lines.append("")

    overall_pass = all(s["pass_flag"] for s in summaries)
    lines.append(f"## OVERALL VERDICT: {'PASS' if overall_pass else 'FAIL'}")
    lines.append("")

    (HERE / "comparison_report.md").write_text("\n".join(lines))


def main() -> int:
    summaries: List[Dict] = []
    pointwise_frames: List[pd.DataFrame] = []
    failures_by_ticker: Dict[str, List[str]] = {}

    for ticker in TICKERS:
        print(f"[{ticker}] evaluating...")
        summary, pw, failures = evaluate_ticker(ticker)
        summaries.append(summary)
        pointwise_frames.append(pw)
        failures_by_ticker[ticker] = failures
        verdict = "PASS" if summary["pass_flag"] else "FAIL"
        print(f"[{ticker}] n={summary['n']}  {verdict}")
        for f in failures:
            print(f"  - {f}")

    pd.DataFrame(summaries).to_csv(HERE / "comparison_summary.csv", index=False)
    pd.concat(pointwise_frames, ignore_index=True).to_csv(
        HERE / "comparison_pointwise.csv", index=False
    )
    write_report(summaries, failures_by_ticker)

    overall_pass = all(s["pass_flag"] for s in summaries)
    print(f"\nOVERALL: {'PASS' if overall_pass else 'FAIL'}")
    print(f"Report: {HERE / 'comparison_report.md'}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())

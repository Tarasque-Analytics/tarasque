"""
test_optimized.py — 4-ticker test run with infrastructure optimizations.

Runs the backtest pipeline on 4 tickers (AAPL, MSFT, XOM, GS) across all
3 horizons, profiling CPU vs GPU XGBoost and tuned n_jobs settings.
Generates comparison plots against old caleb-branch results.

Usage (from project root):
    python -m model.pipeline.test_optimized
    python -m model.pipeline.test_optimized --cpu-only
    python -m model.pipeline.test_optimized --skip-run   # plots only (results must exist)
"""
import argparse
import json
import os
import time
import threading
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Configuration ────────────────────────────────────────────────────────

TEST_TICKERS = ["AAPL", "MSFT", "XOM", "GS"]
HORIZONS = [21, 63, 126]

# Old results from the caleb-branch 82-ticker run (for comparison)
OLD_RESULTS_DIR = Path("model/pipeline/analysis/caleb_results")

# New results go here
NEW_RESULTS_DIR = Path("model/pipeline/results_optimized")

# Plots
PLOTS_DIR = NEW_RESULTS_DIR / "plots"


# ── Resource monitor ─────────────────────────────────────────────────────

class ResourceMonitor:
    """Lightweight background CPU/memory logger."""

    def __init__(self, log_path: Path, interval: float = 5.0):
        self.log_path = log_path
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _loop(self):
        import psutil
        rows = []
        while not self._stop.is_set():
            cpu = psutil.cpu_percent(interval=self.interval)
            mem = psutil.virtual_memory()
            rows.append({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "cpu_pct": cpu,
                "mem_used_gb": mem.used / 1e9,
                "mem_pct": mem.percent,
            })
            # Flush every 12 samples (~60s)
            if len(rows) % 12 == 0:
                pd.DataFrame(rows).to_csv(self.log_path, index=False)
        # Final flush
        if rows:
            pd.DataFrame(rows).to_csv(self.log_path, index=False)


# ── XGB CPU vs GPU profiling ────────────────────────────────────────────

def profile_xgb_device():
    """
    Quick benchmark: XGB CPU hist vs CUDA hist on a synthetic dataset
    matching our typical WF fold size (~3000 rows × 36 features).
    """
    import xgboost as xgb

    np.random.seed(42)
    n_rows, n_features = 3000, 36
    X = np.random.randn(n_rows, n_features)
    y = np.random.randn(n_rows)

    results = {}

    # CPU
    cpu_model = xgb.XGBRegressor(
        n_estimators=100, max_depth=4, learning_rate=0.05,
        tree_method="hist", device="cpu", verbosity=0,
    )
    t0 = time.perf_counter()
    cpu_model.fit(X, y)
    results["cpu_time"] = time.perf_counter() - t0

    # GPU (if available)
    try:
        gpu_model = xgb.XGBRegressor(
            n_estimators=100, max_depth=4, learning_rate=0.05,
            tree_method="hist", device="cuda", verbosity=0,
        )
        # Warm-up
        gpu_model.fit(X[:100], y[:100])
        t0 = time.perf_counter()
        gpu_model.fit(X, y)
        results["gpu_time"] = time.perf_counter() - t0
        results["gpu_available"] = True
    except Exception as e:
        results["gpu_time"] = None
        results["gpu_available"] = False
        results["gpu_error"] = str(e)

    # cuML RF GPU vs sklearn RF CPU
    X32 = X.astype(np.float32)
    y32 = y.astype(np.float32)
    try:
        from cuml.ensemble import RandomForestRegressor as CumlRF
        from sklearn.ensemble import RandomForestRegressor as SkRF

        # sklearn CPU
        sk_rf = SkRF(n_estimators=100, min_samples_leaf=5, n_jobs=-1)
        t0 = time.perf_counter()
        sk_rf.fit(X, y)
        results["rf_sklearn_time"] = time.perf_counter() - t0

        # cuML GPU (warm-up + timed)
        cu_rf = CumlRF(n_estimators=100, min_samples_leaf=5)
        cu_rf.fit(X32[:100], y32[:100])
        t0 = time.perf_counter()
        cu_rf.fit(X32, y32)
        results["rf_cuml_time"] = time.perf_counter() - t0
        results["cuml_available"] = True
    except Exception as e:
        results["cuml_available"] = False
        results["cuml_error"] = str(e)

    return results


# ── n_jobs tuning profile ────────────────────────────────────────────────

def profile_njobs():
    """
    Profile RF and LassoCV with different n_jobs settings
    to find optimal parallelism for 4-ticker concurrent runs.
    """
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.linear_model import LassoCV
    from sklearn.model_selection import TimeSeriesSplit

    np.random.seed(42)
    X = np.random.randn(3000, 36)
    y = np.random.randn(3000)

    results = {}
    n_cores = os.cpu_count() or 8

    # RF: test n_jobs = 2, 4, -1
    for nj in [2, 4, -1]:
        label = str(nj) if nj > 0 else "all"
        rf = RandomForestRegressor(n_estimators=100, min_samples_leaf=5, n_jobs=nj)
        t0 = time.perf_counter()
        rf.fit(X, y)
        results[f"rf_njobs_{label}"] = time.perf_counter() - t0

    # LassoCV: test n_jobs = 2, 4, -1
    for nj in [2, 4, -1]:
        label = str(nj) if nj > 0 else "all"
        lasso = LassoCV(cv=TimeSeriesSplit(n_splits=3), max_iter=10000, n_jobs=nj, alphas=20)
        t0 = time.perf_counter()
        lasso.fit(X, y)
        results[f"lasso_njobs_{label}"] = time.perf_counter() - t0

    results["n_cores"] = n_cores
    return results


# ── Run backtest ─────────────────────────────────────────────────────────

def run_backtest(cpu_only: bool = False):
    """Run the 4-ticker backtest with optimized settings."""
    from .config import load_config
    from .data_loader import fetch_dataset
    from .backtest import BacktestEngine

    dc, mc, bc = load_config()
    dc.tickers = TEST_TICKERS

    # Override results dir
    bc.results_dir = NEW_RESULTS_DIR

    # Parallelism: 2 parallel tickers, n_jobs=4 per model
    # (4 tickers, 2 at a time, each model gets 4 cores = 8 cores busy
    #  on a 16-thread machine this leaves headroom)
    bc.parallel_tickers = 2
    mc.rf_params["n_jobs"] = 4
    mc.xgb_params["n_jobs"] = 4

    if cpu_only:
        mc.xgb_params["device"] = "cpu"

    print(f"\n{'='*60}")
    print(f"  OPTIMIZED TEST RUN: {TEST_TICKERS}")
    print(f"  Horizons: {HORIZONS}")
    print(f"  Parallel tickers: {bc.parallel_tickers}")
    print(f"  RF n_jobs: {mc.rf_params['n_jobs']}")
    print(f"  XGB device: {mc.xgb_params['device']}")
    print(f"  Results: {bc.results_dir}")
    print(f"{'='*60}\n")

    # Fetch data
    print("[TEST] Fetching data...")
    t0 = time.time()
    raw_data = fetch_dataset(dc, force_refresh=False)
    data_time = time.time() - t0
    print(f"[TEST] Data fetched in {data_time:.1f}s")

    # Run backtest
    print("[TEST] Running backtest...")
    t0 = time.time()
    engine = BacktestEngine(dc, mc, bc)
    results = engine.run_sector_sweep(raw_data)
    backtest_time = time.time() - t0

    print(f"\n[TEST] Backtest complete in {backtest_time/60:.1f} min")

    # Save timing summary
    timing = {
        "data_fetch_sec": data_time,
        "backtest_sec": backtest_time,
        "tickers": TEST_TICKERS,
        "parallel_tickers": bc.parallel_tickers,
        "rf_njobs": mc.rf_params["n_jobs"],
        "xgb_device": mc.xgb_params["device"],
    }
    NEW_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(NEW_RESULTS_DIR / "timing.json", "w") as f:
        json.dump(timing, f, indent=2)

    return results, timing


# ── Comparison plots ─────────────────────────────────────────────────────

def generate_comparison_plots():
    """Generate plots comparing new optimized run vs old caleb-branch results."""
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    # Load new results
    new_metrics_path = NEW_RESULTS_DIR / "backtest_results.csv"
    if not new_metrics_path.exists():
        print("[PLOTS] No new results found — skipping plots.")
        return
    new_metrics = pd.read_csv(new_metrics_path)

    # Load old results
    old_metrics_path = OLD_RESULTS_DIR / "backtest_results.csv"
    if not old_metrics_path.exists():
        print("[PLOTS] No old results found — skipping comparison.")
        return
    old_metrics = pd.read_csv(old_metrics_path)

    # Filter old metrics to test tickers only
    old_metrics = old_metrics[old_metrics["ticker"].isin(TEST_TICKERS)]

    # ── Plot 1: RMSE comparison ──────────────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for i, h in enumerate(HORIZONS):
        ax = axes[i]
        old_h = old_metrics[old_metrics["horizon"] == h].set_index("ticker")
        new_h = new_metrics[new_metrics["horizon"] == h].set_index("ticker")
        tickers = sorted(set(old_h.index) & set(new_h.index))
        if not tickers:
            continue
        x = np.arange(len(tickers))
        w = 0.35
        ax.bar(x - w/2, [old_h.loc[t, "rmse"] for t in tickers], w, label="Old run", color="#4C72B0")
        ax.bar(x + w/2, [new_h.loc[t, "rmse"] for t in tickers], w, label="New run", color="#DD8452")
        ax.set_xticks(x)
        ax.set_xticklabels(tickers, rotation=45)
        ax.set_title(f"H={h}")
        ax.set_ylabel("RMSE")
        ax.legend()
    fig.suptitle("RMSE: Old vs Optimized Run", fontsize=14)
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "rmse_comparison.png", dpi=150)
    plt.close()

    # ── Plot 2: MZ R² comparison ─────────────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for i, h in enumerate(HORIZONS):
        ax = axes[i]
        old_h = old_metrics[old_metrics["horizon"] == h].set_index("ticker")
        new_h = new_metrics[new_metrics["horizon"] == h].set_index("ticker")
        tickers = sorted(set(old_h.index) & set(new_h.index))
        if not tickers:
            continue
        x = np.arange(len(tickers))
        w = 0.35
        ax.bar(x - w/2, [old_h.loc[t, "mz_r2"] for t in tickers], w, label="Old run", color="#4C72B0")
        ax.bar(x + w/2, [new_h.loc[t, "mz_r2"] for t in tickers], w, label="New run", color="#DD8452")
        ax.set_xticks(x)
        ax.set_xticklabels(tickers, rotation=45)
        ax.set_title(f"H={h}")
        ax.set_ylabel("MZ R²")
        ax.legend()
    fig.suptitle("Mincer-Zarnowitz R²: Old vs Optimized Run", fontsize=14)
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "mz_r2_comparison.png", dpi=150)
    plt.close()

    # ── Plot 3: Ensemble weight evolution (from weights_history CSVs) ─
    fig, axes = plt.subplots(len(TEST_TICKERS), 3, figsize=(16, 4 * len(TEST_TICKERS)))
    if len(TEST_TICKERS) == 1:
        axes = axes.reshape(1, -1)
    for row, ticker in enumerate(TEST_TICKERS):
        for col, h in enumerate(HORIZONS):
            ax = axes[row, col]
            wh_path = NEW_RESULTS_DIR / f"weights_history_{ticker}_H{h}.csv"
            if not wh_path.exists():
                ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
                ax.set_title(f"{ticker} H={h}")
                continue
            wh = pd.read_csv(wh_path)
            for model_name in ["w_XGB", "w_RF", "w_LassoCV"]:
                if model_name in wh.columns:
                    label = model_name.replace("w_", "")
                    ax.plot(wh["step"], wh[model_name], label=label, linewidth=1.5)
            ax.set_ylim(0, 0.6)
            ax.set_title(f"{ticker} H={h}")
            ax.set_xlabel("WF Step")
            ax.set_ylabel("Weight")
            if row == 0 and col == 0:
                ax.legend(fontsize=8)
    fig.suptitle("Ensemble Weight Evolution Over Walk-Forward Steps", fontsize=14, y=1.01)
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "weight_evolution.png", dpi=150, bbox_inches="tight")
    plt.close()

    # ── Plot 4: Per-model predictions vs blended (H=21 only) ─────────
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    for idx, ticker in enumerate(TEST_TICKERS):
        ax = axes[idx // 2, idx % 2]
        pred_path = NEW_RESULTS_DIR / f"predictions_{ticker}_H21.csv"
        if not pred_path.exists():
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(ticker)
            continue
        pred = pd.read_csv(pred_path)
        pred["date"] = pd.to_datetime(pred["date"])
        # Subsample for readability
        step = max(1, len(pred) // 200)
        pred = pred.iloc[::step]

        ax.plot(pred["date"], pred["y_true"], "k-", alpha=0.5, linewidth=0.8, label="Realized")
        ax.plot(pred["date"], pred["y_pred"], "b-", linewidth=1.0, label="Blended")
        for mname, color in [("pred_XGB", "#DD8452"), ("pred_RF", "#55A868"), ("pred_LassoCV", "#C44E52")]:
            if mname in pred.columns:
                ax.plot(pred["date"], pred[mname], "--", color=color, linewidth=0.7,
                        alpha=0.7, label=mname.replace("pred_", ""))
        ax.set_title(f"{ticker} H=21")
        ax.set_ylabel("Annualized Vol")
        ax.legend(fontsize=7, loc="upper right")
        ax.tick_params(axis="x", rotation=30)
    fig.suptitle("Per-Model Predictions vs Blended (H=21)", fontsize=14)
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "per_model_predictions.png", dpi=150)
    plt.close()

    # ── Plot 5: Pinball loss comparison (new run only) ───────────────
    if all(col in new_metrics.columns for col in ["pinball_10", "pinball_50", "pinball_90"]):
        fig, ax = plt.subplots(figsize=(10, 6))
        taus = ["pinball_10", "pinball_50", "pinball_90"]
        tau_labels = ["τ=0.10", "τ=0.50", "τ=0.90"]
        for h in HORIZONS:
            h_data = new_metrics[new_metrics["horizon"] == h]
            means = [h_data[t].mean() for t in taus]
            ax.plot(tau_labels, means, "o-", label=f"H={h}", linewidth=2)
        ax.set_ylabel("Pinball Loss")
        ax.set_title("Pinball (Quantile) Loss by Horizon")
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(PLOTS_DIR / "pinball_loss.png", dpi=150)
        plt.close()

    # ── Plot 6: CV RMSE from weights history ─────────────────────────
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    for idx, ticker in enumerate(TEST_TICKERS):
        ax = axes[idx // 2, idx % 2]
        wh_path = NEW_RESULTS_DIR / f"weights_history_{ticker}_H21.csv"
        if not wh_path.exists():
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(ticker)
            continue
        wh = pd.read_csv(wh_path)
        for col in ["cv_rmse_XGB", "cv_rmse_RF", "cv_rmse_LassoCV"]:
            if col in wh.columns:
                label = col.replace("cv_rmse_", "")
                ax.plot(wh["step"], wh[col], label=label, linewidth=1.5)
        ax.set_title(f"{ticker} H=21 — CV RMSE per Model")
        ax.set_xlabel("WF Step")
        ax.set_ylabel("CV RMSE")
        ax.legend(fontsize=8)
    fig.suptitle("Cross-Validation RMSE by Model Over Time", fontsize=14)
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "cv_rmse_evolution.png", dpi=150)
    plt.close()

    print(f"[PLOTS] {len(list(PLOTS_DIR.glob('*.png')))} plots saved to {PLOTS_DIR}")


# ── Performance report ───────────────────────────────────────────────────

def generate_report(xgb_profile: dict, njobs_profile: dict, timing: dict):
    """Generate a markdown performance report."""
    report_lines = [
        "# Optimized Test Run Report",
        "",
        f"**Tickers:** {', '.join(TEST_TICKERS)}",
        f"**Horizons:** {HORIZONS}",
        f"**Date:** {time.strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
        "## XGBoost CPU vs GPU Profile",
        "",
        f"| Device | Time (s) |",
        f"|--------|----------|",
        f"| CPU    | {xgb_profile.get('cpu_time', 'N/A'):.3f}   |" if xgb_profile.get('cpu_time') else "| CPU | N/A |",
    ]

    if xgb_profile.get("gpu_available"):
        gpu_t = xgb_profile["gpu_time"]
        cpu_t = xgb_profile["cpu_time"]
        speedup = cpu_t / gpu_t if gpu_t > 0 else 0
        report_lines.append(f"| CUDA   | {gpu_t:.3f}   |")
        report_lines.append("")
        if speedup > 1:
            report_lines.append(f"**GPU is {speedup:.1f}× faster** at this scale (3000×36).")
        else:
            report_lines.append(f"**CPU is {1/speedup:.1f}× faster** at this scale (3000×36). GPU overhead exceeds gains for small datasets.")
            report_lines.append("Recommendation: use `device='cpu'` unless dataset grows significantly.")
    else:
        report_lines.extend([
            "| CUDA   | N/A (not available) |",
            "",
            f"GPU error: {xgb_profile.get('gpu_error', 'unknown')}",
        ])

    # cuML RF section
    if xgb_profile.get("cuml_available"):
        sk_t = xgb_profile.get("rf_sklearn_time", 0)
        cu_t = xgb_profile.get("rf_cuml_time", 0)
        rf_speedup = sk_t / cu_t if cu_t > 0 else 0
        report_lines.extend([
            "",
            "### Random Forest: sklearn CPU vs cuML GPU",
            "",
            f"| Backend | Time (s) |",
            f"|---------|----------|",
            f"| sklearn (CPU, n_jobs=-1) | {sk_t:.3f} |",
            f"| cuML (GPU) | {cu_t:.3f} |",
            "",
            f"**cuML GPU RF is {rf_speedup:.1f}× faster** than sklearn CPU.",
        ])

    report_lines.extend([
        "",
        "---",
        "",
        "## n_jobs Parallelism Profile",
        "",
        f"Machine cores: {njobs_profile.get('n_cores', 'N/A')}",
        "",
        "### Random Forest",
        "",
        "| n_jobs | Time (s) |",
        "|--------|----------|",
    ])
    for nj in ["2", "4", "all"]:
        key = f"rf_njobs_{nj}"
        val = njobs_profile.get(key)
        report_lines.append(f"| {nj:>6} | {val:.3f}   |" if val else f"| {nj:>6} | N/A |")

    report_lines.extend([
        "",
        "### LassoCV",
        "",
        "| n_jobs | Time (s) |",
        "|--------|----------|",
    ])
    for nj in ["2", "4", "all"]:
        key = f"lasso_njobs_{nj}"
        val = njobs_profile.get(key)
        report_lines.append(f"| {nj:>6} | {val:.3f}   |" if val else f"| {nj:>6} | N/A |")

    report_lines.extend([
        "",
        "---",
        "",
        "## Backtest Timing",
        "",
        f"| Phase | Time |",
        f"|-------|------|",
        f"| Data fetch | {timing.get('data_fetch_sec', 0):.1f}s |",
        f"| Backtest   | {timing.get('backtest_sec', 0)/60:.1f} min |",
        f"| **Total**  | **{(timing.get('data_fetch_sec', 0) + timing.get('backtest_sec', 0))/60:.1f} min** |",
        "",
        f"Parallel tickers: {timing.get('parallel_tickers', 'N/A')}",
        f"RF n_jobs: {timing.get('rf_njobs', 'N/A')}",
        f"XGB device: {timing.get('xgb_device', 'N/A')}",
        "",
        "---",
        "",
        "## Comparison vs Old Run",
        "",
    ])

    # Load metrics for comparison table
    new_path = NEW_RESULTS_DIR / "backtest_results.csv"
    old_path = OLD_RESULTS_DIR / "backtest_results.csv"
    if new_path.exists() and old_path.exists():
        new_m = pd.read_csv(new_path)
        old_m = pd.read_csv(old_path)
        old_m = old_m[old_m["ticker"].isin(TEST_TICKERS)]

        report_lines.extend([
            "| Ticker | H | Old RMSE | New RMSE | Old R² | New R² | RMSE Δ% |",
            "|--------|---|----------|----------|--------|--------|---------|",
        ])
        for _, row in new_m.iterrows():
            t, h = row["ticker"], row["horizon"]
            old_row = old_m[(old_m["ticker"] == t) & (old_m["horizon"] == h)]
            if old_row.empty:
                continue
            old_rmse = old_row.iloc[0]["rmse"]
            new_rmse = row["rmse"]
            old_r2 = old_row.iloc[0]["mz_r2"]
            new_r2 = row["mz_r2"]
            delta_pct = (new_rmse - old_rmse) / old_rmse * 100
            report_lines.append(
                f"| {t} | {h} | {old_rmse:.4f} | {new_rmse:.4f} | "
                f"{old_r2:.3f} | {new_r2:.3f} | {delta_pct:+.1f}% |"
            )

        # Pinball loss summary (new run only)
        if "pinball_10" in new_m.columns:
            report_lines.extend([
                "",
                "### Pinball Loss (New Run)",
                "",
                "| Ticker | H | τ=0.10 | τ=0.50 | τ=0.90 | Asymmetry (90/10) |",
                "|--------|---|--------|--------|--------|-------------------|",
            ])
            for _, row in new_m.iterrows():
                asym = row["pinball_90"] / row["pinball_10"] if row["pinball_10"] > 0 else float("nan")
                report_lines.append(
                    f"| {row['ticker']} | {row['horizon']} | "
                    f"{row['pinball_10']:.4f} | {row['pinball_50']:.4f} | "
                    f"{row['pinball_90']:.4f} | {asym:.2f} |"
                )

    report_lines.extend([
        "",
        "---",
        "",
        "## Plots",
        "",
        "- ![RMSE Comparison](plots/rmse_comparison.png)",
        "- ![MZ R² Comparison](plots/mz_r2_comparison.png)",
        "- ![Weight Evolution](plots/weight_evolution.png)",
        "- ![Per-Model Predictions](plots/per_model_predictions.png)",
        "- ![Pinball Loss](plots/pinball_loss.png)",
        "- ![CV RMSE Evolution](plots/cv_rmse_evolution.png)",
    ])

    report_path = NEW_RESULTS_DIR / "test_run_report.md"
    with open(report_path, "w") as f:
        f.write("\n".join(report_lines))
    print(f"[REPORT] Written to {report_path}")


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Optimized 4-ticker test run")
    parser.add_argument("--cpu-only", action="store_true", help="Force XGB to CPU (skip GPU)")
    parser.add_argument("--skip-run", action="store_true", help="Skip backtest, generate plots only")
    parser.add_argument("--skip-profile", action="store_true", help="Skip XGB/n_jobs profiling")
    args = parser.parse_args()

    NEW_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    xgb_profile = {}
    njobs_profile = {}
    timing = {}

    if not args.skip_run:
        # 1. Start resource monitor
        monitor = None
        try:
            import psutil
            monitor = ResourceMonitor(NEW_RESULTS_DIR / "resource_log.csv")
            monitor.start()
            print("\n[MONITOR] Resource logging started")
        except ImportError:
            print("\n[MONITOR] psutil not installed — skipping resource monitoring")

        # 2. Run backtest FIRST (before any CUDA profiling, to avoid
        #    fork deadlock — CUDA contexts are not fork-safe)
        results, timing = run_backtest(cpu_only=args.cpu_only)

        if monitor:
            monitor.stop()
            print("[MONITOR] Resource logging stopped")

        # 3. Profile AFTER backtest (safe: no more forking)
        if not args.skip_profile:
            print("\n[PROFILE] XGBoost CPU vs GPU...")
            xgb_profile = profile_xgb_device()
            print(f"  CPU: {xgb_profile.get('cpu_time', 'N/A'):.3f}s")
            if xgb_profile.get("gpu_available"):
                print(f"  GPU: {xgb_profile['gpu_time']:.3f}s")
                speedup = xgb_profile["cpu_time"] / xgb_profile["gpu_time"]
                print(f"  {'GPU' if speedup > 1 else 'CPU'} is {max(speedup, 1/speedup):.1f}× faster")
            else:
                print(f"  GPU: not available ({xgb_profile.get('gpu_error', '')})")

            print("\n[PROFILE] n_jobs parallelism...")
            njobs_profile = profile_njobs()
            for key, val in sorted(njobs_profile.items()):
                if key != "n_cores":
                    print(f"  {key}: {val:.3f}s")

            # Save profiles
            with open(NEW_RESULTS_DIR / "profiles.json", "w") as f:
                json.dump({"xgb": xgb_profile, "njobs": njobs_profile}, f, indent=2)
    else:
        # Load existing profiles/timing if available
        profiles_path = NEW_RESULTS_DIR / "profiles.json"
        if profiles_path.exists():
            with open(profiles_path) as f:
                profiles = json.load(f)
            xgb_profile = profiles.get("xgb", {})
            njobs_profile = profiles.get("njobs", {})
        timing_path = NEW_RESULTS_DIR / "timing.json"
        if timing_path.exists():
            with open(timing_path) as f:
                timing = json.load(f)

    # 4. Generate comparison plots
    print("\n[PLOTS] Generating comparison plots...")
    generate_comparison_plots()

    # 5. Generate report
    generate_report(xgb_profile, njobs_profile, timing)

    print("\n[DONE] All outputs in:", NEW_RESULTS_DIR)


if __name__ == "__main__":
    main()

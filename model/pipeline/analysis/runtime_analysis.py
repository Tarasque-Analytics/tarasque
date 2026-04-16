"""
Runtime Analysis & Speed Optimization
======================================
Analyzes the caleb-hardware-backtest-run profiling data and resource utilization.
BA branch has no detailed timing data — runtime estimated from commit timestamps.
"""

import re, warnings
import numpy as np
import pandas as pd
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore", category=FutureWarning)

BASE = Path(__file__).parent
CALEB_MON = BASE / "caleb_results" / "monitoring"
PLOTS = BASE / "plots"
PLOTS.mkdir(exist_ok=True)


def parse_profile_lines(log_path):
    """Extract PROFILE timing data from batch_run.log."""
    rows = []
    pattern = re.compile(
        r"\[PROFILE\]\s+(\w+)\s+model fit time.*?"
        r"LassoCV:\s+([\d.]+)s.*?"
        r"RF:\s+([\d.]+)s.*?"
        r"XGB:\s+([\d.]+)s.*?"
        r"total:\s+([\d.]+)s"
    )
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
    return pd.DataFrame(rows)


def parse_batch_times(log_path):
    """Extract batch completion times."""
    rows = []
    pattern = re.compile(r"Batch\s+(\d+)\s+complete in\s+([\d.]+)\s+min")
    with open(log_path) as f:
        for line in f:
            m = pattern.search(line)
            if m:
                rows.append({
                    "batch": int(m.group(1)),
                    "minutes": float(m.group(2)),
                })
    return pd.DataFrame(rows)


def main():
    log_path = CALEB_MON / "batch_run.log"
    resource_path = CALEB_MON / "resource_log.csv"

    # ── 1. PROFILE data ──────────────────────────────────────────────
    prof = parse_profile_lines(log_path)
    print(f"Profiled tickers: {len(prof)}")

    print("\n=== PER-MODEL TIMING (all tickers) ===")
    for col in ["lasso_s", "rf_s", "xgb_s", "total_s"]:
        vals = prof[col]
        print(f"  {col:10s}: mean={vals.mean():7.1f}s  median={vals.median():7.1f}s  "
              f"std={vals.std():6.1f}s  min={vals.min():7.1f}s  max={vals.max():7.1f}s")

    # Percentage breakdown
    total_lasso = prof["lasso_s"].sum()
    total_rf = prof["rf_s"].sum()
    total_xgb = prof["xgb_s"].sum()
    total_all = total_lasso + total_rf + total_xgb
    print(f"\n=== AGGREGATE TRAINING TIME ===")
    print(f"  LassoCV: {total_lasso/3600:.1f}h ({100*total_lasso/total_all:.1f}%)")
    print(f"  RF:      {total_rf/3600:.1f}h ({100*total_rf/total_all:.1f}%)")
    print(f"  XGBoost: {total_xgb/3600:.1f}h ({100*total_xgb/total_all:.1f}%)")
    print(f"  Total:   {total_all/3600:.1f}h (model fit only, excludes data loading/features)")

    # ── 2. Batch timing ──────────────────────────────────────────────
    batches = parse_batch_times(log_path)
    print(f"\n=== BATCH TIMING (27 batches) ===")
    print(f"  Mean:   {batches['minutes'].mean():.1f} min")
    print(f"  Median: {batches['minutes'].median():.1f} min")
    print(f"  Std:    {batches['minutes'].std():.1f} min")
    print(f"  Min:    {batches['minutes'].min():.1f} min (batch {batches.loc[batches['minutes'].idxmin(), 'batch']})")
    print(f"  Max:    {batches['minutes'].max():.1f} min (batch {batches.loc[batches['minutes'].idxmax(), 'batch']})")
    print(f"  Total:  {batches['minutes'].sum():.1f} min = {batches['minutes'].sum()/60:.1f} hrs")

    # ── 3. Resource utilization ──────────────────────────────────────
    res = pd.read_csv(resource_path)
    res["timestamp"] = pd.to_datetime(res["timestamp"])

    # Exclude idle periods (before/after backtest)
    active = res[res["cpu_pct"] > 10].copy()
    print(f"\n=== RESOURCE UTILIZATION (active period, {len(active)} samples) ===")
    for col, label in [("cpu_pct", "CPU%"), ("ram_pct", "RAM%"),
                       ("gpu_pct", "GPU%"), ("gpu_vram_used_mb", "VRAM MB")]:
        vals = active[col]
        print(f"  {label:10s}: mean={vals.mean():6.1f}  median={vals.median():6.1f}  "
              f"p95={vals.quantile(0.95):6.1f}  max={vals.max():6.1f}")

    # GPU idle fraction during active period
    gpu_idle_frac = (active["gpu_pct"] < 5).mean()
    print(f"\n  GPU idle (<5%) during active period: {100*gpu_idle_frac:.1f}% of time")
    print(f"  GPU active (>5%) during active period: {100*(1-gpu_idle_frac):.1f}% of time")

    # ── 4. Bottleneck analysis ───────────────────────────────────────
    print("\n=== BOTTLENECK ANALYSIS ===")
    # Per-ticker: model fit takes total_s, but batch takes ~80min for 3 tickers
    # The batch wall-clock includes data loading, feature computation, and model fit
    avg_ticker_fit = prof["total_s"].mean()
    avg_batch_min = batches["minutes"].mean()
    overhead_per_batch = avg_batch_min * 60 - avg_ticker_fit  # approximate (parallel execution complicates this)
    print(f"  Avg ticker model fit: {avg_ticker_fit:.0f}s ({avg_ticker_fit/60:.1f} min)")
    print(f"  Avg batch wall-clock: {avg_batch_min:.1f} min")
    print(f"  3 tickers run in parallel → effective per-batch model time: {avg_ticker_fit/60:.1f} min")
    print(f"  Overhead (data load + features + I/O): ~{overhead_per_batch/60:.1f} min per batch")

    # With 2x cores (5950X scenario)
    # RF and LassoCV scale near-linearly with cores (n_jobs=-1)
    # XGBoost on GPU doesn't benefit from more CPU cores
    rf_lasso_frac = (total_rf + total_lasso) / total_all
    xgb_frac = total_xgb / total_all
    speedup_2x_cores = 1 / (xgb_frac + rf_lasso_frac / 2)
    print(f"\n  Theoretical speedup with 2x CPU cores (5950X scenario):")
    print(f"    RF+LassoCV fraction: {100*rf_lasso_frac:.1f}%")
    print(f"    XGB (GPU, core-independent): {100*xgb_frac:.1f}%")
    print(f"    Amdahl's law speedup: {speedup_2x_cores:.2f}x")
    print(f"    Estimated runtime: {36.5/speedup_2x_cores:.1f} hrs (vs 36.5 hrs actual)")

    # ── 5. Optimization estimates ────────────────────────────────────
    print("\n=== OPTIMIZATION ESTIMATES ===")
    base_hrs = 36.5

    opts = [
        ("Arch Linux native (eliminate WSL2 overhead)",
         "10-20% I/O + syscall speedup on /mnt/c/ paths",
         base_hrs * 0.85, base_hrs * 0.90),
        ("cuML RF on GPU (replace sklearn RF)",
         "RF is 37% of fit time; cuML RF ~5-10x faster on RTX 3070 Ti",
         base_hrs * 0.70, base_hrs * 0.80),
        ("Parallelism tuning (4 tickers/batch, n_jobs=4/model)",
         "Better core utilization, less thread contention",
         base_hrs * 0.80, base_hrs * 0.90),
        ("Feature matrix caching (precompute once per ticker)",
         "Eliminate redundant feature computation at each WF step",
         base_hrs * 0.90, base_hrs * 0.95),
        ("XGB CPU hist (skip GPU for small datasets)",
         "GPU overhead may exceed gains at ~3K rows; profile needed",
         base_hrs * 0.95, base_hrs * 1.05),  # Could go either way
    ]

    print(f"  {'Optimization':<55s} {'Low est':>8s} {'High est':>8s} {'Saving':>8s}")
    print(f"  {'-'*55} {'-'*8} {'-'*8} {'-'*8}")
    for name, desc, low, high in opts:
        saving = base_hrs - (low + high) / 2
        print(f"  {name:<55s} {low:6.1f}h  {high:6.1f}h  {saving:+5.1f}h")

    # Combined optimistic scenario
    combined_factor = 0.85 * 0.75 * 0.85  # Linux * cuML RF * parallelism
    combined_hrs = base_hrs * combined_factor
    print(f"\n  Combined optimistic (Linux + cuML RF + parallelism): ~{combined_hrs:.0f}h")
    print(f"  Combined on 5950X equivalent: ~{combined_hrs / speedup_2x_cores:.0f}h")

    # ── 6. Plots ─────────────────────────────────────────────────────

    # Model fit breakdown
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle("Caleb Branch: Runtime Profiling (i7-11700K + RTX 3070 Ti)", fontsize=14, fontweight="bold")

    # Per-ticker stacked bar
    ax = axes[0]
    prof_sorted = prof.sort_values("total_s", ascending=False).head(40)
    x = range(len(prof_sorted))
    ax.barh(x, prof_sorted["xgb_s"] / 60, color="#e74c3c", label="XGBoost (GPU)")
    ax.barh(x, prof_sorted["rf_s"] / 60, left=prof_sorted["xgb_s"] / 60, color="#2ecc71", label="Random Forest")
    ax.barh(x, prof_sorted["lasso_s"] / 60, left=(prof_sorted["xgb_s"] + prof_sorted["rf_s"]) / 60,
            color="#3498db", label="LassoCV")
    ax.set_yticks(x)
    ax.set_yticklabels(prof_sorted["ticker"], fontsize=7)
    ax.set_xlabel("Training Time (minutes)", fontsize=11)
    ax.set_title("Model Fit Time by Ticker (top 40)", fontsize=12)
    ax.legend(fontsize=9)
    ax.invert_yaxis()

    # Batch runtime bar chart
    ax = axes[1]
    colors = ["#e74c3c" if m > 90 else "#f39c12" if m > 85 else "#2ecc71" for m in batches["minutes"]]
    ax.bar(batches["batch"], batches["minutes"], color=colors, edgecolor="k", linewidth=0.3)
    ax.axhline(batches["minutes"].mean(), color="k", linestyle="--", alpha=0.5, label=f"Mean: {batches['minutes'].mean():.1f} min")
    ax.set_xlabel("Batch Number", fontsize=11)
    ax.set_ylabel("Runtime (minutes)", fontsize=11)
    ax.set_title("Batch Runtime", fontsize=12)
    ax.legend(fontsize=9)

    plt.tight_layout()
    plt.savefig(PLOTS / "runtime_profiling.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nSaved: {PLOTS / 'runtime_profiling.png'}")

    # Resource utilization time series
    fig, axes = plt.subplots(3, 1, figsize=(16, 10), sharex=True)
    fig.suptitle("Resource Utilization Over 36.5-Hour Run", fontsize=14, fontweight="bold")

    elapsed_hrs = (res["timestamp"] - res["timestamp"].iloc[0]).dt.total_seconds() / 3600

    ax = axes[0]
    ax.plot(elapsed_hrs, res["cpu_pct"], color="#e74c3c", alpha=0.7, linewidth=0.5)
    ax.fill_between(elapsed_hrs, res["cpu_pct"], alpha=0.2, color="#e74c3c")
    ax.set_ylabel("CPU %", fontsize=11)
    ax.set_ylim(0, 105)
    ax.axhline(res[res["cpu_pct"]>10]["cpu_pct"].mean(), color="k", linestyle="--", alpha=0.3)

    ax = axes[1]
    ax.plot(elapsed_hrs, res["ram_pct"], color="#3498db", alpha=0.7, linewidth=0.5)
    ax.fill_between(elapsed_hrs, res["ram_pct"], alpha=0.2, color="#3498db")
    ax.set_ylabel("RAM %", fontsize=11)
    ax.set_ylim(0, 50)

    ax = axes[2]
    ax.plot(elapsed_hrs, res["gpu_pct"], color="#2ecc71", alpha=0.7, linewidth=0.5)
    ax.fill_between(elapsed_hrs, res["gpu_pct"], alpha=0.2, color="#2ecc71")
    ax.set_ylabel("GPU %", fontsize=11)
    ax.set_xlabel("Elapsed Hours", fontsize=11)
    ax.set_ylim(0, 105)

    # Add batch markers
    batch_times_cumulative = batches["minutes"].cumsum() / 60
    for ax_i in axes:
        for bt in batch_times_cumulative:
            ax_i.axvline(bt, color="gray", alpha=0.15, linewidth=0.5)

    plt.tight_layout()
    plt.savefig(PLOTS / "resource_utilization.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {PLOTS / 'resource_utilization.png'}")

    # Pie chart: aggregate time split
    fig, ax = plt.subplots(figsize=(7, 7))
    sizes = [total_lasso, total_rf, total_xgb]
    labels = [f"LassoCV\n{total_lasso/3600:.1f}h ({100*total_lasso/total_all:.0f}%)",
              f"Random Forest\n{total_rf/3600:.1f}h ({100*total_rf/total_all:.0f}%)",
              f"XGBoost (GPU)\n{total_xgb/3600:.1f}h ({100*total_xgb/total_all:.0f}%)"]
    colors = ["#3498db", "#2ecc71", "#e74c3c"]
    ax.pie(sizes, labels=labels, colors=colors, autopct="", startangle=90,
           textprops={"fontsize": 12})
    ax.set_title("Aggregate Model Training Time Split\n(79 tickers × 3 horizons)", fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.savefig(PLOTS / "training_time_split.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {PLOTS / 'training_time_split.png'}")


if __name__ == "__main__":
    main()

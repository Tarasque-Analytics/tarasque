"""
monitor.py — Resource monitoring daemon for overnight batch backtests.

Runs alongside batch_backtest.py, logging CPU/RAM/GPU usage and batch progress
to model/pipeline/results/monitoring/.

Usage (from project root):
    python -m model.pipeline.monitor
    python -m model.pipeline.monitor --interval 30   # check every 30s
"""
import argparse
import csv
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

# ── Paths ────────────────────────────────────────────────────────────────
MONITOR_DIR = Path(__file__).resolve().parent / "results" / "monitoring"
RESOURCE_LOG = MONITOR_DIR / "resource_log.csv"
LATEST_STATUS = MONITOR_DIR / "latest_status.txt"
ALERTS_LOG = MONITOR_DIR / "alerts.log"
PROGRESS_JSON = MONITOR_DIR / "progress.json"
BATCH_LOG = MONITOR_DIR / "batch_run.log"

# ── Thresholds ───────────────────────────────────────────────────────────
RAM_WARN_PCT = 85
RAM_CRIT_PCT = 90
CONSECUTIVE_CHECKS_TO_ALERT = 3


def get_gpu_stats() -> dict:
    """Query nvidia-smi for GPU utilization and VRAM."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            return {
                "gpu_pct": float(parts[0]),
                "gpu_vram_used_mb": float(parts[1]),
                "gpu_vram_total_mb": float(parts[2]),
            }
    except Exception:
        pass
    return {"gpu_pct": 0.0, "gpu_vram_used_mb": 0.0, "gpu_vram_total_mb": 0.0}


def get_batch_progress() -> dict:
    """Read progress.json written by batch_backtest.py."""
    try:
        if PROGRESS_JSON.exists():
            with open(PROGRESS_JSON) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def write_csv_row(row: dict):
    """Append a row to resource_log.csv, creating header if needed."""
    file_exists = RESOURCE_LOG.exists() and RESOURCE_LOG.stat().st_size > 0
    fieldnames = [
        "timestamp", "ram_used_gb", "ram_total_gb", "ram_pct",
        "cpu_pct", "gpu_pct", "gpu_vram_used_mb", "gpu_vram_total_mb",
        "batch_num", "total_batches", "tickers_done", "tickers_failed",
    ]
    with open(RESOURCE_LOG, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def write_status(row: dict, progress: dict):
    """Overwrite latest_status.txt with human-readable snapshot."""
    now = row["timestamp"]
    lines = [
        f"=== Volarbmodel Batch Monitor ===",
        f"Updated: {now}",
        f"",
        f"--- Resources ---",
        f"RAM:  {row['ram_used_gb']:.1f} / {row['ram_total_gb']:.1f} GB  ({row['ram_pct']:.0f}%)",
        f"CPU:  {row['cpu_pct']:.0f}%",
        f"GPU:  {row['gpu_pct']:.0f}%   VRAM: {row['gpu_vram_used_mb']:.0f} / {row['gpu_vram_total_mb']:.0f} MB",
    ]

    if progress:
        cur = progress.get("current_batch", "?")
        total = progress.get("total_batches", "?")
        done = len(progress.get("tickers_completed", []))
        failed = len(progress.get("tickers_failed", []))
        elapsed = progress.get("elapsed_hours", 0)
        eta = progress.get("estimated_remaining_hours", 0)

        lines += [
            f"",
            f"--- Batch Progress ---",
            f"Batch:    {cur} / {total}",
            f"Tickers:  {done} done, {failed} failed",
            f"Elapsed:  {elapsed:.1f} hrs",
            f"ETA:      {eta:.1f} hrs remaining",
        ]

        recent = progress.get("tickers_completed", [])[-5:]
        if recent:
            lines.append(f"Recent:   {', '.join(recent)}")

        failed_list = progress.get("tickers_failed", [])
        if failed_list:
            lines.append(f"Failed:   {', '.join(failed_list)}")
    else:
        lines += ["", "--- Batch Progress ---", "Waiting for batch_backtest to start..."]

    lines.append("")
    with open(LATEST_STATUS, "w") as f:
        f.write("\n".join(lines))


def write_alert(level: str, message: str):
    """Append an alert to alerts.log."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with open(ALERTS_LOG, "a") as f:
        f.write(f"[{now}] [{level}] {message}\n")
    print(f"  *** ALERT [{level}] {message}")


def main():
    parser = argparse.ArgumentParser(description="Resource monitor for batch backtests")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between checks (default: 60)")
    args = parser.parse_args()

    MONITOR_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[MONITOR] Logging to {MONITOR_DIR}")
    print(f"[MONITOR] Interval: {args.interval}s | RAM warn: {RAM_WARN_PCT}% | RAM crit: {RAM_CRIT_PCT}%")
    print(f"[MONITOR] Press Ctrl+C to stop\n")

    consecutive_warn = 0
    consecutive_crit = 0

    # Prime CPU measurement (first call always returns 0)
    psutil.cpu_percent(interval=None)

    try:
        while True:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

            # Gather metrics
            mem = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=1)
            gpu = get_gpu_stats()
            progress = get_batch_progress()

            row = {
                "timestamp": now,
                "ram_used_gb": round(mem.used / (1024**3), 2),
                "ram_total_gb": round(mem.total / (1024**3), 2),
                "ram_pct": round(mem.percent, 1),
                "cpu_pct": round(cpu, 1),
                "gpu_pct": gpu["gpu_pct"],
                "gpu_vram_used_mb": gpu["gpu_vram_used_mb"],
                "gpu_vram_total_mb": gpu["gpu_vram_total_mb"],
                "batch_num": progress.get("current_batch", 0),
                "total_batches": progress.get("total_batches", 0),
                "tickers_done": len(progress.get("tickers_completed", [])),
                "tickers_failed": len(progress.get("tickers_failed", [])),
            }

            # Write outputs
            write_csv_row(row)
            write_status(row, progress)

            # Console output
            prog_str = ""
            if progress:
                prog_str = f" | Batch {row['batch_num']}/{row['total_batches']} ({row['tickers_done']} tickers)"
            print(f"[{now}] RAM {row['ram_pct']}% | CPU {row['cpu_pct']}% | GPU {row['gpu_pct']}%{prog_str}")

            # RAM safety checks
            if mem.percent >= RAM_CRIT_PCT:
                consecutive_crit += 1
                consecutive_warn = 0
                if consecutive_crit >= CONSECUTIVE_CHECKS_TO_ALERT:
                    write_alert("CRITICAL", f"RAM at {mem.percent:.0f}% for {consecutive_crit} consecutive checks!")
            elif mem.percent >= RAM_WARN_PCT:
                consecutive_warn += 1
                consecutive_crit = 0
                if consecutive_warn >= CONSECUTIVE_CHECKS_TO_ALERT:
                    write_alert("WARNING", f"RAM at {mem.percent:.0f}% for {consecutive_warn} consecutive checks")
            else:
                consecutive_warn = 0
                consecutive_crit = 0

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n[MONITOR] Stopped by user")


if __name__ == "__main__":
    main()

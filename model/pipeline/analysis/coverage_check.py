"""
coverage_check.py -- Per-ticker scalar offset to calibrate quantile coverage.

For each (ticker, horizon), finds delta such that:
    coverage(y_pred_q15 - delta) = TARGET_COVERAGE (0.85)

The offset is computed from the empirical distribution of (y_true - y_pred_q15):
    delta = -quantile(y_true - y_pred_q15, 1 - TARGET_COVERAGE)

Outputs
-------
  results/q15_coverage_offsets.csv   -- (ticker, horizon, delta, coverage_raw, coverage_adj)
  Console summary with per-horizon aggregates

Usage
-----
  python -m model.pipeline.analysis.coverage_check
  python -m model.pipeline.analysis.coverage_check --target 0.85
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ..utils import DECIMAL_PRECISION, round_for_output

RESULTS_DIR = Path("model/pipeline/results")
PREDS_CSV   = RESULTS_DIR / "all_predictions.csv"
TARGET_COV  = 0.85  # tau=0.15 => want 85% of y_true above the floor


def compute_offsets(target: float = TARGET_COV) -> pd.DataFrame:
    df = pd.read_csv(PREDS_CSV)
    rows = []

    for (ticker, horizon), grp in df.groupby(["ticker", "horizon"]):
        sub = grp.dropna(subset=["y_true", "y_pred_q15"])
        if len(sub) < 50:
            continue

        residuals = sub["y_true"].values - sub["y_pred_q15"].values
        coverage_raw = float((sub["y_true"] > sub["y_pred_q15"]).mean())

        # Find delta: want P(y_true > q15 - delta) = target
        # => P(residual > -delta) = target
        # => P(residual <= -delta) = 1 - target
        # => -delta = quantile(residuals, 1 - target)
        # => delta = -quantile(residuals, 1 - target)
        delta = -float(np.quantile(residuals, 1 - target))

        # Verify
        coverage_adj = float((sub["y_true"] > (sub["y_pred_q15"] - delta)).mean())

        rows.append({
            "ticker":       ticker,
            "horizon":      int(horizon),
            "delta":        round(delta, 6),
            "coverage_raw": round(coverage_raw, 4),
            "coverage_adj": round(coverage_adj, 4),
            "n":            int(len(sub)),
        })

    return pd.DataFrame(rows).sort_values(["ticker", "horizon"])


def main():
    parser = argparse.ArgumentParser(description="Q15 coverage calibration offsets")
    parser.add_argument("--target", type=float, default=TARGET_COV,
                        help=f"Target coverage (default {TARGET_COV})")
    args = parser.parse_args()

    print(f"[COVERAGE] Computing per-ticker offsets for target={args.target:.0%}...")
    offsets = compute_offsets(target=args.target)

    out_path = RESULTS_DIR / "q15_coverage_offsets.csv"
    round_for_output(offsets, DECIMAL_PRECISION).to_csv(out_path, index=False)
    print(f"[COVERAGE] Offsets saved -> {out_path}  ({len(offsets)} rows)")

    # Summary
    print(f"\n{'='*65}")
    print(f"  Q15 COVERAGE CALIBRATION  (target={args.target:.0%})")
    print(f"{'='*65}")
    for h in sorted(offsets["horizon"].unique()):
        sub = offsets[offsets["horizon"] == h]
        print(f"\n  H={h}:")
        print(f"    Coverage raw:  mean={sub['coverage_raw'].mean():.4f}  "
              f"min={sub['coverage_raw'].min():.4f}  max={sub['coverage_raw'].max():.4f}")
        print(f"    Coverage adj:  mean={sub['coverage_adj'].mean():.4f}  "
              f"min={sub['coverage_adj'].min():.4f}  max={sub['coverage_adj'].max():.4f}")
        print(f"    Delta:         mean={sub['delta'].mean():.6f}  "
              f"min={sub['delta'].min():.6f}  max={sub['delta'].max():.6f}")
        print(f"    Tickers at target (+/-0.02): "
              f"{((sub['coverage_adj'] >= args.target - 0.02) & (sub['coverage_adj'] <= args.target + 0.02)).sum()}/{len(sub)}")

    # Flag tickers with extreme deltas (> 2 std from mean per horizon)
    print(f"\n  Outlier deltas (>2 std from horizon mean):")
    for h in sorted(offsets["horizon"].unique()):
        sub = offsets[offsets["horizon"] == h]
        mu, sigma = sub["delta"].mean(), sub["delta"].std()
        outliers = sub[abs(sub["delta"] - mu) > 2 * sigma]
        if len(outliers) > 0:
            for _, row in outliers.iterrows():
                print(f"    {row['ticker']} H={h}: delta={row['delta']:.6f} "
                      f"(coverage {row['coverage_raw']:.3f} -> {row['coverage_adj']:.3f})")
        else:
            print(f"    H={h}: none")

    print(f"\n{'='*65}")


if __name__ == "__main__":
    main()

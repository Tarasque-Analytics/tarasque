"""
refresh_q15_offsets.py — Recompute per-(ticker, horizon) q15 floor offsets on
v10+ predictions.

The previous q15_coverage_offsets.csv was computed on v8 corpus data (step_days=63).
v10+ predictions need fresh per-ticker scalar shifts on y_pred_q15 to bring
realized coverage back to the 0.85 target.

For each (ticker, horizon):
  current_coverage = mean(y_true > y_pred_q15)
  iterate scalar shift `delta` such that y_true > (y_pred_q15 - delta) hits 0.85

Outputs:
  model/pipeline/results/q15_coverage_offsets_v10.csv
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..utils import DECIMAL_PRECISION, round_for_output


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS = REPO_ROOT / "model" / "pipeline" / "results"
TARGET_COVERAGE = 0.85


def find_offset(y_true: np.ndarray, y_pred_q15: np.ndarray,
                target: float = TARGET_COVERAGE) -> tuple[float, float]:
    """Binary search a scalar `delta` such that mean(y_true > q15 - delta) ≈ target.

    Positive delta lowers the floor (increases coverage).
    Returns (delta, achieved_coverage).
    """
    if len(y_true) < 50:
        return (0.0, float(np.nan))
    # Bound search: shifting by ±2*std should be more than enough
    sd = np.nanstd(y_pred_q15)
    lo, hi = -3 * sd, 3 * sd
    for _ in range(40):
        mid = (lo + hi) / 2
        cov = float(np.mean(y_true > (y_pred_q15 - mid)))
        if cov < target:
            lo = mid
        else:
            hi = mid
        if abs(cov - target) < 1e-4:
            break
    achieved = float(np.mean(y_true > (y_pred_q15 - mid)))
    return (float(mid), achieved)


def main():
    src = RESULTS / "v10_canary_combined_predictions.csv"
    if not src.exists():
        print(f"[Q15] Need {src.name}; run aggregate_canaries first.")
        return
    df = pd.read_csv(src, parse_dates=["date"])
    if "y_pred_q15" not in df.columns:
        print("[Q15] No y_pred_q15 column; abort.")
        return

    rows = []
    for (tk, h), g in df.groupby(["ticker", "horizon"], observed=True):
        g = g.dropna(subset=["y_true", "y_pred_q15"])
        if len(g) < 100:
            continue
        cov_before = float((g["y_true"] > g["y_pred_q15"]).mean())
        delta, cov_after = find_offset(g["y_true"].values, g["y_pred_q15"].values)
        rows.append({
            "ticker": tk,
            "horizon": int(h),
            "n": int(len(g)),
            "coverage_before": cov_before,
            "delta": delta,
            "coverage_after": cov_after,
        })
    out = pd.DataFrame(rows).sort_values(["horizon", "ticker"])
    out = round_for_output(out, DECIMAL_PRECISION)
    out_path = RESULTS / "q15_coverage_offsets_v10.csv"
    out.to_csv(out_path, index=False)
    print(f"[Q15] Wrote {out_path.name}: {len(out)} (ticker × horizon) rows")

    # Summary
    print()
    for h in sorted(out["horizon"].unique()):
        sub = out[out["horizon"] == h]
        print(f"H={int(h)}: mean coverage before={sub['coverage_before'].mean():.3f}, "
              f"mean delta={sub['delta'].mean():.4f}, "
              f"mean coverage after={sub['coverage_after'].mean():.3f}, "
              f"in [0.83, 0.87]: {((sub['coverage_after']>=0.83)&(sub['coverage_after']<=0.87)).sum()}/{len(sub)}")


if __name__ == "__main__":
    main()

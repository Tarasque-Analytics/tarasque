"""
trail_dynamics_ic.py — Does *where the trail has been* predict forward outcomes
                       beyond *where the trail is now*?

Builds on regime_signal_test.py. That script measures whether the current
quadrant_rank (a STATIC snapshot of β_mkt × β_mz) has Spearman IC against
forward (return | drawdown | vol). This script tests whether trail DYNAMICS
features — velocity, recent drift in β_mz, drift direction — add IC beyond
the static quadrant.

If yes: the visual slug-trail framework is empirically informative beyond a
single-point classifier. If no: the trail looks pretty but adds nothing
predictive over knowing where the ticker is right now.

Features computed per (ticker, asof) snapshot:
  - velocity        = sqrt((Δβ_mkt)² + (Δβ_mz)²) from prior snapshot
  - drift_mz_6mo    = OLS slope of β_mz over last 6 snapshots
  - drift_mkt_6mo   = OLS slope of β_mkt over last 6 snapshots
  - drift_mz_3mo    = OLS slope of β_mz over last 3 snapshots (faster signal)
  - direction_angle = arctan2(Δβ_mz, Δβ_mkt), wrapped to [0, 2π)

Outputs:
  model/pipeline/results/validation/trail_dynamics_ic.csv     — IC table
  model/pipeline/results/validation/trail_dynamics_summary.md — markdown brief

Usage:
  python -m model.pipeline.analysis.trail_dynamics_ic
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .regime_signal_test import (
    load_trails,
    load_closes,
    compute_forward_outcomes,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT = REPO_ROOT / "model" / "pipeline" / "results" / "validation"

# Trail snapshots are monthly. 6 snapshots = 6 months of slope.
DRIFT_WINDOW_LONG = 6
DRIFT_WINDOW_SHORT = 3
HORIZONS = (21, 63, 126)
METRICS = ("ret", "dd", "vol")


def _slope(y: np.ndarray) -> float:
    """OLS slope of y vs equally-spaced x. NaN if insufficient finite values."""
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(y)
    if mask.sum() < 3:
        return np.nan
    x = np.arange(len(y), dtype=float)[mask]
    y = y[mask]
    x_demeaned = x - x.mean()
    var = float((x_demeaned ** 2).sum())
    if var == 0:
        return np.nan
    return float((x_demeaned * (y - y.mean())).sum() / var)


def add_dynamics_features(trails: pd.DataFrame) -> pd.DataFrame:
    """Add per-snapshot dynamics features to a long-form trail dataframe."""
    out = []
    for ticker, g in trails.groupby("ticker"):
        g = g.sort_values("asof").reset_index(drop=True).copy()
        g["d_mkt"] = g["beta_mkt"].diff()
        g["d_mz"]  = g["beta_mz_h21"].diff()
        g["velocity"] = np.sqrt(g["d_mkt"] ** 2 + g["d_mz"] ** 2)
        g["direction_angle"] = np.arctan2(g["d_mz"], g["d_mkt"]) % (2 * np.pi)

        # Rolling slopes — require at least DRIFT_WINDOW_SHORT/LONG observations
        drift_mz_long  = np.full(len(g), np.nan)
        drift_mkt_long = np.full(len(g), np.nan)
        drift_mz_short = np.full(len(g), np.nan)
        for i in range(len(g)):
            lo_long  = max(0, i - DRIFT_WINDOW_LONG  + 1)
            lo_short = max(0, i - DRIFT_WINDOW_SHORT + 1)
            if i - lo_long + 1 >= 3:
                drift_mz_long[i]  = _slope(g["beta_mz_h21"].iloc[lo_long:i+1].values)
                drift_mkt_long[i] = _slope(g["beta_mkt"].iloc[lo_long:i+1].values)
            if i - lo_short + 1 >= 3:
                drift_mz_short[i] = _slope(g["beta_mz_h21"].iloc[lo_short:i+1].values)
        g["drift_mz_6mo"]  = drift_mz_long
        g["drift_mkt_6mo"] = drift_mkt_long
        g["drift_mz_3mo"]  = drift_mz_short
        out.append(g)
    return pd.concat(out, ignore_index=True)


def compute_ic_table(joined: pd.DataFrame, dyn_features: list[str]) -> pd.DataFrame:
    """For each (horizon × metric) cell, compute Spearman IC of each feature.

    Reports:
      - ic_quadrant       (baseline from regime_signal_test)
      - ic_<dyn_feature>  (one column per dynamics feature)
      - ic_stack          (joint via fitted-rank linear combo of quadrant_rank + drift_mz_6mo)
    """
    rows = []
    for h in HORIZONS:
        for metric in METRICS:
            col = f"fwd_{metric}_h{h}"
            req = ["quadrant_rank", col] + dyn_features
            sub = joined.dropna(subset=req)
            if len(sub) < 50:
                continue

            row = {"horizon": h, "metric": metric, "n": len(sub),
                   "ic_quadrant": float(sub["quadrant_rank"].corr(sub[col], method="spearman"))}
            for f in dyn_features:
                row[f"ic_{f}"] = float(sub[f].corr(sub[col], method="spearman"))

            # Stack: equal-weight rank of (quadrant_rank + drift_mz_6mo).
            # Rank each predictor, sum ranks, then Spearman the sum vs outcome.
            # Cheap proxy for "do they combine usefully?".
            r1 = sub["quadrant_rank"].rank()
            r2 = sub["drift_mz_6mo"].rank()
            stack = r1 + r2
            row["ic_stack_quadrant_plus_drift_mz_6mo"] = float(stack.corr(sub[col], method="spearman"))
            rows.append(row)
    return pd.DataFrame(rows)


def write_markdown(ic: pd.DataFrame, out: Path) -> None:
    lines = ["# Trail Dynamics IC Test", "",
             "Does *where the trail has been* add predictive content over the",
             "static quadrant_rank? Reports Spearman IC vs forward outcomes.",
             "",
             "Convention:",
             "- `ret`: forward log return.  Lower is bad → expect NEGATIVE IC for risk-up features.",
             "- `dd`: forward drawdown (negative log diff).  Lower is bad → expect NEGATIVE IC.",
             "- `vol`: forward realized vol.  Higher = more risk → expect POSITIVE IC.",
             "", "## IC table", ""]
    cols = [c for c in ic.columns if c not in ("horizon", "metric", "n")]
    header = "| horizon | metric | n | " + " | ".join(cols) + " |"
    sep    = "|---|---|---|" + "|".join(["---"] * len(cols)) + "|"
    lines += [header, sep]
    for _, r in ic.iterrows():
        cells = [f"{r['horizon']}", r["metric"], f"{int(r['n'])}"]
        cells += [f"{r[c]:+.3f}" for c in cols]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "## Interpretation guide", "",
              "**Trail dynamics are additive** if `ic_drift_mz_6mo` (or `_3mo`) has",
              "a meaningful Spearman IC with the SAME SIGN as the matching `ic_quadrant`",
              "row — e.g., for `vol`, both positive. That means drift is independently",
              "tracking the same risk gradient the quadrant captures.",
              "",
              "**Trail dynamics REPLACE the quadrant** if the stack IC is",
              "meaningfully larger than `ic_quadrant` alone. That would suggest the",
              "drift axis carries more signal than the static rank.",
              "",
              "**Trail dynamics are noise** if `ic_drift_*` hovers near zero and the",
              "stack IC is no better than `ic_quadrant` alone."]
    out.write_text("\n".join(lines), encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    print("[TRAIL_IC] Loading trails...")
    trails = load_trails(restrict_to_v10=False)
    if trails.empty:
        print("[TRAIL_IC] No trails found. Did you run regime_trail.py first?")
        return 1
    print(f"  {len(trails)} trail snapshots across {trails['ticker'].nunique()} tickers")

    print("[TRAIL_IC] Adding dynamics features...")
    trails = add_dynamics_features(trails)

    print("[TRAIL_IC] Loading closes for forward outcomes...")
    closes = load_closes()

    print("[TRAIL_IC] Computing forward outcomes...")
    fwd = compute_forward_outcomes(trails, closes)
    # Re-attach the dynamics features that compute_forward_outcomes drops
    joined = fwd.merge(
        trails[["ticker", "asof", "velocity", "drift_mz_6mo",
                "drift_mkt_6mo", "drift_mz_3mo", "direction_angle"]],
        on=["ticker", "asof"], how="left",
    )

    print(f"  {len(joined)} joined rows after forward-outcome attachment")

    dyn_features = ["velocity", "drift_mz_6mo", "drift_mkt_6mo",
                    "drift_mz_3mo", "direction_angle"]
    print("[TRAIL_IC] Computing IC table...")
    ic = compute_ic_table(joined, dyn_features)

    if ic.empty:
        print("[TRAIL_IC] Insufficient data for any (horizon, metric) cell.")
        return 1

    csv_path = OUT / "trail_dynamics_ic.csv"
    md_path  = OUT / "trail_dynamics_summary.md"
    ic.to_csv(csv_path, index=False)
    write_markdown(ic, md_path)
    print(f"[TRAIL_IC] Wrote {csv_path}")
    print(f"[TRAIL_IC] Wrote {md_path}")

    print("\n=== IC TABLE ===")
    # Print compact view
    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(ic.to_string(index=False))

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

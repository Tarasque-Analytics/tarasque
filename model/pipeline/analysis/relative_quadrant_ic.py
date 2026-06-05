"""
relative_quadrant_ic.py — Does ticker-RELATIVE quadrant classification beat
                          the absolute (β=1.0) threshold version?

Current `regime_signal_test.py` classifies each (ticker, snapshot) into
Q1/Q2/Q3/Q4 using ABSOLUTE thresholds: β_mkt < 1.0 vs ≥ 1.0 and
β_mz ≤ 1.0 vs > 1.0. The user's VRP-percentile principle says this should
be ticker-conditional — ORCL whose β_mz historically averages 1.2 should be
classified relative to its OWN distribution, not the universal 1.0.

This script computes the same Spearman IC test as `regime_signal_test.py`
under three threshold conventions:
  1. ABSOLUTE       — universal 1.0 cutoffs (the existing baseline)
  2. RELATIVE_FULL  — per-ticker median across all snapshots (mild forward leak
                       on threshold; cleanest test of the IDEA)
  3. RELATIVE_EXP   — per-ticker EXPANDING-window median requiring ≥ N prior
                       snapshots (deployable signal, no leak, less data)

If RELATIVE_FULL and RELATIVE_EXP both beat ABSOLUTE meaningfully on IC vs
forward outcomes, the ordinal/relative framing is empirically validated.
If only FULL beats and EXP doesn't, the forward leak is doing the work.

Outputs:
  model/pipeline/results/validation/relative_quadrant_ic.csv
  model/pipeline/results/validation/relative_quadrant_summary.md

Usage:
  python -m model.pipeline.analysis.relative_quadrant_ic
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .regime_signal_test import (
    load_trails, load_closes, compute_forward_outcomes,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT = REPO_ROOT / "model" / "pipeline" / "results" / "validation"

HORIZONS = (21, 63, 126)
METRICS = ("ret", "dd", "vol")
MIN_HISTORY_FOR_EXPANDING = 8  # need this many prior snapshots before classifying

# Same ordering as regime_signal_test.QUADRANT_RANK
QUADRANT_RANK = {
    "Q3-genuinely-calm": 0,
    "Q4-mega-cap-buffer": 1,
    "Q1-stealth-event-risk": 2,
    "Q2-idiosync-plus-systematic": 3,
}


def classify_one(b_mkt: float, b_mz: float,
                 cut_mkt: float, cut_mz: float) -> str:
    """Same quadrant labels as regime_signal_test, parameterized cutoffs."""
    if pd.isna(b_mkt) or pd.isna(b_mz):
        return "n/a"
    if b_mkt < cut_mkt and b_mz <= cut_mz:
        return "Q3-genuinely-calm"
    if b_mkt < cut_mkt and b_mz > cut_mz:
        return "Q1-stealth-event-risk"
    if b_mkt >= cut_mkt and b_mz <= cut_mz:
        return "Q4-mega-cap-buffer"
    return "Q2-idiosync-plus-systematic"


def add_quadrants(trails: pd.DataFrame) -> pd.DataFrame:
    """Add three quadrant columns: absolute, relative_full, relative_exp."""
    out = []
    for ticker, g in trails.groupby("ticker"):
        g = g.sort_values("asof").reset_index(drop=True).copy()

        # ABSOLUTE: cutoff 1.0 for both axes
        g["q_abs"] = [classify_one(m, z, 1.0, 1.0)
                      for m, z in zip(g["beta_mkt"], g["beta_mz_h21"])]

        # RELATIVE_FULL: per-ticker median across entire trail
        med_mkt_full = g["beta_mkt"].median()
        med_mz_full  = g["beta_mz_h21"].median()
        g["q_rel_full"] = [classify_one(m, z, med_mkt_full, med_mz_full)
                           for m, z in zip(g["beta_mkt"], g["beta_mz_h21"])]

        # RELATIVE_EXP: expanding median over PRIOR snapshots only
        rel_exp = []
        for i in range(len(g)):
            if i < MIN_HISTORY_FOR_EXPANDING:
                rel_exp.append("n/a-history")
                continue
            prior = g.iloc[:i]
            cut_mkt = prior["beta_mkt"].median()
            cut_mz  = prior["beta_mz_h21"].median()
            rel_exp.append(classify_one(g["beta_mkt"].iloc[i],
                                        g["beta_mz_h21"].iloc[i],
                                        cut_mkt, cut_mz))
        g["q_rel_exp"] = rel_exp
        out.append(g)
    full = pd.concat(out, ignore_index=True)
    for col in ("q_abs", "q_rel_full", "q_rel_exp"):
        full[f"{col}_rank"] = full[col].map(QUADRANT_RANK)
    return full


def compute_ic_table(joined: pd.DataFrame) -> pd.DataFrame:
    """For each (horizon × metric), compute Spearman IC under each scheme.

    Each row is one (horizon, metric, scheme). 'scheme' ∈ {abs, rel_full, rel_exp}.
    Critical: restrict each scheme's IC to the SAME set of observations that
    have a valid rank under that scheme (rel_exp drops the first 8 snapshots).
    For apples-to-apples comparison we ALSO report each on the COMMON subset
    where all three are valid.
    """
    rows = []
    for scheme, rank_col in [("abs", "q_abs_rank"),
                             ("rel_full", "q_rel_full_rank"),
                             ("rel_exp",  "q_rel_exp_rank")]:
        for h in HORIZONS:
            for metric in METRICS:
                col = f"fwd_{metric}_h{h}"
                # Per-scheme own subset
                sub = joined.dropna(subset=[rank_col, col])
                if len(sub) < 50:
                    continue
                ic_own = float(sub[rank_col].corr(sub[col], method="spearman"))
                rows.append({"scheme": scheme, "horizon": h, "metric": metric,
                             "subset": "own", "n": len(sub), "ic": ic_own})

    # Common subset: all three schemes valid
    common = joined.dropna(subset=["q_abs_rank", "q_rel_full_rank", "q_rel_exp_rank"])
    for scheme, rank_col in [("abs", "q_abs_rank"),
                             ("rel_full", "q_rel_full_rank"),
                             ("rel_exp",  "q_rel_exp_rank")]:
        for h in HORIZONS:
            for metric in METRICS:
                col = f"fwd_{metric}_h{h}"
                sub = common.dropna(subset=[col])
                if len(sub) < 50:
                    continue
                ic_common = float(sub[rank_col].corr(sub[col], method="spearman"))
                rows.append({"scheme": scheme, "horizon": h, "metric": metric,
                             "subset": "common", "n": len(sub), "ic": ic_common})
    return pd.DataFrame(rows)


def write_markdown(ic: pd.DataFrame, out: Path) -> None:
    lines = ["# Relative Quadrant IC Test", "",
             "Does per-ticker-relative threshold classification (β median of own",
             "history) beat universal absolute (β=1.0) cutoffs?",
             "", "Sign expectations: positive for `vol`, negative for `ret` and `dd`.",
             ""]

    for subset_kind in ("common", "own"):
        lines += [f"## Subset: `{subset_kind}`", ""]
        sub = ic[ic["subset"] == subset_kind].copy()
        if sub.empty:
            lines.append("_no rows_")
            continue
        # Pivot: rows = (horizon, metric), cols = scheme
        piv = sub.pivot_table(index=["horizon", "metric"], columns="scheme",
                              values="ic").reset_index()
        # add n column from any scheme
        n_per_pair = sub.groupby(["horizon", "metric"])["n"].first().reset_index()
        piv = piv.merge(n_per_pair, on=["horizon", "metric"])
        cols = ["horizon", "metric", "n", "abs", "rel_full", "rel_exp"]
        cols = [c for c in cols if c in piv.columns]
        piv = piv[cols]
        # Add winner column
        if {"abs", "rel_full", "rel_exp"}.issubset(piv.columns):
            def winner(row):
                # For vol: highest positive IC wins.
                # For ret / dd: lowest (most negative) IC wins.
                metric = row["metric"]
                scores = {s: row[s] for s in ("abs", "rel_full", "rel_exp")
                          if pd.notna(row[s])}
                if not scores:
                    return "—"
                if metric == "vol":
                    return max(scores, key=lambda k: scores[k])
                else:
                    return min(scores, key=lambda k: scores[k])
            piv["best"] = piv.apply(winner, axis=1)

        header = "| " + " | ".join(piv.columns) + " |"
        sep    = "|" + "|".join(["---"] * len(piv.columns)) + "|"
        lines += [header, sep]
        for _, r in piv.iterrows():
            cells = []
            for c in piv.columns:
                v = r[c]
                if isinstance(v, (int, np.integer)):
                    cells.append(str(int(v)))
                elif isinstance(v, float):
                    cells.append(f"{v:+.3f}")
                else:
                    cells.append(str(v))
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    lines += ["## How to read",
              "",
              "- `abs`: universal β=1.0 cutoffs (existing classifier)",
              "- `rel_full`: per-ticker median over the FULL trail (clean test of the idea, mild lookahead)",
              "- `rel_exp`: per-ticker expanding-window median (≥8 prior snapshots; deployable)",
              "",
              "**Verdict logic:**",
              "- If `rel_full` AND `rel_exp` both beat `abs` on vol IC → ordinal framing is empirically additive.",
              "- If only `rel_full` beats `abs` → forward leak is doing the work; not deployable as-is.",
              "- If neither beats `abs` → ticker-relative framing doesn't help for THIS classifier.",
              "",
              "Use the `common` subset for apples-to-apples comparison (same observations across schemes)."]
    out.write_text("\n".join(lines), encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    print("[REL_IC] Loading trails...")
    trails = load_trails(restrict_to_v10=False)
    if trails.empty:
        print("[REL_IC] No trails found.")
        return 1
    print(f"  {len(trails)} snapshots across {trails['ticker'].nunique()} tickers")

    print("[REL_IC] Classifying under absolute, relative_full, relative_exp...")
    trails = add_quadrants(trails)

    print("[REL_IC] Loading closes for forward outcomes...")
    closes = load_closes()
    print("[REL_IC] Computing forward outcomes...")
    fwd = compute_forward_outcomes(trails, closes)
    # Re-attach the three quadrant ranks
    joined = fwd.merge(
        trails[["ticker", "asof", "q_abs_rank", "q_rel_full_rank", "q_rel_exp_rank"]],
        on=["ticker", "asof"], how="left",
    )
    print(f"  {len(joined)} joined rows")
    print(f"  q_abs valid: {joined['q_abs_rank'].notna().sum()}")
    print(f"  q_rel_full valid: {joined['q_rel_full_rank'].notna().sum()}")
    print(f"  q_rel_exp valid: {joined['q_rel_exp_rank'].notna().sum()}")

    print("[REL_IC] Computing IC table...")
    ic = compute_ic_table(joined)

    if ic.empty:
        print("[REL_IC] Insufficient data.")
        return 1

    csv_path = OUT / "relative_quadrant_ic.csv"
    md_path  = OUT / "relative_quadrant_summary.md"
    ic.to_csv(csv_path, index=False)
    write_markdown(ic, md_path)
    print(f"[REL_IC] Wrote {csv_path}")
    print(f"[REL_IC] Wrote {md_path}")

    # Compact stdout view: pivot for vol on the common subset
    print("\n=== COMMON SUBSET IC (apples-to-apples) ===")
    common = ic[ic.subset == "common"]
    piv = common.pivot_table(index=["horizon", "metric"], columns="scheme",
                             values="ic").reset_index()
    with pd.option_context("display.width", 200, "display.max_columns", None,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(piv.to_string(index=False))

    print("\n=== OWN SUBSET IC (each scheme on its own valid rows) ===")
    own = ic[ic.subset == "own"]
    piv = own.pivot_table(index=["horizon", "metric"], columns="scheme",
                          values="ic").reset_index()
    with pd.option_context("display.width", 200, "display.max_columns", None,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(piv.to_string(index=False))

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

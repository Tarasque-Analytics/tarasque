"""
regime_returns.py — Forward return distributions conditioned on regime quadrant.

Validates whether the (β_mkt, β_mz) quadrant labels carry economic content.
For each (ticker, quarter-end) row in the regime_trail outputs, compute the
realized forward return at H=21 / H=63 / H=126. Bucket by quadrant and report
the distribution.

If the regime classification is meaningful, we expect:
  - Q3 (genuinely-calm): tighter, more centered return distribution
  - Q1 (stealth event-risk): wider distribution, fatter left tail
  - Q2 (idiosync + systematic): widest, fattest tails
  - Q4 (mega-cap-buffer): wide but more symmetric (driven by market beta)

Outputs:
  model/pipeline/results/regime_trail/regime_returns.csv (per row)
  model/pipeline/results/regime_trail/regime_returns_summary.csv (per quadrant × horizon)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import load_config
from ..data_loader import ParquetStore
from ..utils import DECIMAL_PRECISION, round_for_output


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "model" / "pipeline" / "results"
TRAIL_DIR = RESULTS_DIR / "regime_trail"


def classify(beta_mkt: float, beta_mz: float) -> str:
    if pd.isna(beta_mkt) or pd.isna(beta_mz):
        return "n/a"
    if beta_mkt < 1.0 and beta_mz <= 1.0:
        return "Q3-genuinely-calm"
    if beta_mkt < 1.0 and beta_mz > 1.0:
        return "Q1-stealth-event-risk"
    if beta_mkt >= 1.0 and beta_mz <= 1.0:
        return "Q4-mega-cap-buffer"
    return "Q2-idiosync-plus-systematic"


def main():
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    ohlcv = store.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    ohlcv = ohlcv.drop_duplicates(subset=["date", "ticker"], keep="last")
    closes = ohlcv.pivot(index="date", columns="ticker", values="prc").ffill()
    log_close = np.log(closes)

    # Aggregate all per-ticker trails
    trails = []
    for p in TRAIL_DIR.glob("*_trail.csv"):
        df = pd.read_csv(p, parse_dates=["asof"])
        trails.append(df)
    if not trails:
        print("[REGIME_RETURNS] No trail files found; run regime_trail first.")
        return
    df = pd.concat(trails, ignore_index=True)
    df["quadrant"] = [classify(b_mkt, b_mz) for b_mkt, b_mz
                      in zip(df["beta_mkt"], df["beta_mz_h21"])]

    # For each row, look up forward log-return at H=21 / H=63 / H=126
    rows = []
    for _, r in df.iterrows():
        tk = r["ticker"]
        if tk not in log_close.columns:
            continue
        d = pd.Timestamp(r["asof"])
        if d not in log_close.index:
            # snap to nearest preceding date
            past = log_close.index[log_close.index <= d]
            if len(past) == 0:
                continue
            d = past[-1]
        idx = log_close.index.get_loc(d)
        out = {"ticker": tk, "asof": r["asof"], "quadrant": r["quadrant"],
               "beta_mkt": r["beta_mkt"], "beta_mz_h21": r["beta_mz_h21"]}
        for h in (21, 63, 126):
            j = idx + h
            if j >= len(log_close):
                out[f"fwd_ret_h{h}"] = np.nan
            else:
                out[f"fwd_ret_h{h}"] = float(log_close[tk].iloc[j] - log_close[tk].iloc[idx])
        rows.append(out)

    out_df = pd.DataFrame(rows)
    out_df = round_for_output(out_df, DECIMAL_PRECISION)
    out_path = TRAIL_DIR / "regime_returns.csv"
    out_df.to_csv(out_path, index=False)
    print(f"[REGIME_RETURNS] Wrote {out_path.name} ({len(out_df)} rows)")

    # Per-quadrant summary stats
    summary_rows = []
    for q in sorted(out_df["quadrant"].unique()):
        for h in (21, 63, 126):
            col = f"fwd_ret_h{h}"
            sub = out_df[out_df["quadrant"] == q][col].dropna()
            if len(sub) < 5:
                continue
            summary_rows.append({
                "quadrant": q,
                "horizon": h,
                "n": len(sub),
                "mean": sub.mean(),
                "median": sub.median(),
                "std": sub.std(),
                "p10": sub.quantile(0.10),
                "p25": sub.quantile(0.25),
                "p75": sub.quantile(0.75),
                "p90": sub.quantile(0.90),
                "pct_negative": (sub < 0).mean(),
            })
    summary = pd.DataFrame(summary_rows)
    summary = round_for_output(summary, DECIMAL_PRECISION)
    sum_path = TRAIL_DIR / "regime_returns_summary.csv"
    summary.to_csv(sum_path, index=False)
    print(f"[REGIME_RETURNS] Wrote {sum_path.name}")

    print()
    print("=" * 80)
    print("  Per-quadrant forward return distribution (log returns)")
    print("=" * 80)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

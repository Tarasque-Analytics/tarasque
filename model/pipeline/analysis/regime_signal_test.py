"""
regime_signal_test.py — Test economic content of the regime classifier.

For each (ticker, monthly snapshot) in the v10+ regime_trail outputs, look up:
  - Forward 21d/63d/126d realized return
  - Forward max drawdown over the same horizon
  - Forward realized vol over the same horizon

Then:
1. Compare distributions across quadrants (Q1/Q2/Q3/Q4)
2. Compute Spearman IC of quadrant-ordered-by-risk vs realized forward risk metric
3. Run the same test on β_mz alone (continuous) — does the residual carry signal?

This tests whether the REGIME LABEL (not the vol forecast) has predictive content.
The hypothesis: Q2 > Q1 > Q4 > Q3 in expected forward drawdown / vol; if the data
matches this ordering, the regime classifier is economically informative.

Outputs in model/pipeline/results/validation/:
  regime_signal_distribution.csv — per-quadrant forward-outcome stats
  regime_signal_ic.csv — IC of quadrant rank vs realized forward outcomes
  regime_signal_summary.md — meeting-grade brief
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import load_config
from ..data_loader import ParquetStore
from ..utils import DECIMAL_PRECISION, round_for_output


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS = REPO_ROOT / "model" / "pipeline" / "results"
TRAIL_DIR = RESULTS / "regime_trail"
OUT = RESULTS / "validation"


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


# Hypothesized ordering by forward RISK (low → high)
QUADRANT_RANK = {
    "Q3-genuinely-calm": 0,
    "Q4-mega-cap-buffer": 1,
    "Q1-stealth-event-risk": 2,
    "Q2-idiosync-plus-systematic": 3,
}


def load_trails(restrict_to_v10: bool = True) -> pd.DataFrame:
    """Combine per-ticker trail snapshots. By default restrict to the 26 v10+
    tickers (whose trails were regenerated on v10_canary_combined_predictions.csv)
    rather than mixing in stale v8 trails left on disk."""
    v10_tickers = None
    if restrict_to_v10:
        v10_path = RESULTS / "v10_canary_combined_predictions.csv"
        if v10_path.exists():
            v10_tickers = set(pd.read_csv(v10_path, usecols=["ticker"])
                              ["ticker"].unique())
    frames = []
    for f in TRAIL_DIR.glob("*_trail.csv"):
        ticker = f.stem.replace("_trail", "")
        if v10_tickers is not None and ticker not in v10_tickers:
            continue
        df = pd.read_csv(f, parse_dates=["asof"])
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["quadrant"] = [classify(b_mkt, b_mz) for b_mkt, b_mz
                      in zip(df["beta_mkt"], df["beta_mz_h21"])]
    df["quadrant_rank"] = df["quadrant"].map(QUADRANT_RANK)
    return df


def load_closes() -> pd.DataFrame:
    dc, _, _ = load_config()
    s = ParquetStore(dc.base_dir)
    ohlcv = s.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    ohlcv = ohlcv.drop_duplicates(subset=["date", "ticker"], keep="last")
    return ohlcv.pivot(index="date", columns="ticker", values="prc").ffill()


def compute_forward_outcomes(trails: pd.DataFrame, closes: pd.DataFrame) -> pd.DataFrame:
    """For each (ticker, snapshot), compute forward realized return, drawdown, vol."""
    rows = []
    for _, r in trails.iterrows():
        tk = r["ticker"]
        d = pd.Timestamp(r["asof"])
        if tk not in closes.columns:
            continue
        # snap to nearest preceding date
        idx = closes.index.searchsorted(d, side="right") - 1
        if idx < 0 or idx >= len(closes):
            continue
        out = {
            "ticker": tk,
            "asof": r["asof"],
            "quadrant": r["quadrant"],
            "quadrant_rank": r["quadrant_rank"],
            "beta_mkt": r["beta_mkt"],
            "beta_mz_h21": r["beta_mz_h21"],
        }
        log_close_t = np.log(closes[tk].iloc[idx])
        for h in (21, 63, 126):
            j = idx + h
            if j >= len(closes):
                out[f"fwd_ret_h{h}"] = np.nan
                out[f"fwd_dd_h{h}"] = np.nan
                out[f"fwd_vol_h{h}"] = np.nan
                continue
            window = closes[tk].iloc[idx + 1: j + 1]
            if window.dropna().empty:
                out[f"fwd_ret_h{h}"] = np.nan
                out[f"fwd_dd_h{h}"] = np.nan
                out[f"fwd_vol_h{h}"] = np.nan
                continue
            log_close_end = np.log(window.iloc[-1])
            log_returns = np.log(window).diff().dropna()
            out[f"fwd_ret_h{h}"] = float(log_close_end - log_close_t)
            out[f"fwd_dd_h{h}"] = float(np.log(window.min()) - log_close_t)
            out[f"fwd_vol_h{h}"] = float(log_returns.std() * np.sqrt(252))
        rows.append(out)
    return pd.DataFrame(rows)


def quadrant_distribution_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Per-quadrant × horizon distribution stats for forward outcomes."""
    stats_rows = []
    for q in sorted(df["quadrant"].dropna().unique()):
        for h in (21, 63, 126):
            sub = df[df["quadrant"] == q].dropna(
                subset=[f"fwd_ret_h{h}", f"fwd_dd_h{h}", f"fwd_vol_h{h}"])
            if len(sub) < 10:
                continue
            stats_rows.append({
                "quadrant": q,
                "horizon": h,
                "n": len(sub),
                "ret_mean": float(sub[f"fwd_ret_h{h}"].mean()),
                "ret_std": float(sub[f"fwd_ret_h{h}"].std()),
                "ret_median": float(sub[f"fwd_ret_h{h}"].median()),
                "ret_pct_negative": float((sub[f"fwd_ret_h{h}"] < 0).mean()),
                "dd_mean": float(sub[f"fwd_dd_h{h}"].mean()),
                "dd_p10": float(sub[f"fwd_dd_h{h}"].quantile(0.10)),
                "dd_p25": float(sub[f"fwd_dd_h{h}"].quantile(0.25)),
                "vol_mean": float(sub[f"fwd_vol_h{h}"].mean()),
                "vol_std": float(sub[f"fwd_vol_h{h}"].std()),
            })
    return pd.DataFrame(stats_rows)


def compute_ic(df: pd.DataFrame) -> pd.DataFrame:
    """Spearman IC: quadrant_rank (0..3 = low→high risk) vs realized risk metric.

    Tests:
      - "ret IC": rank vs forward return — expect NEGATIVE (high-risk → lower returns?)
      - "dd IC": rank vs forward drawdown — expect NEGATIVE (more risky = worse DD)
      - "vol IC": rank vs forward vol — expect POSITIVE (more risky = more vol)

    Also runs continuous β_mz IC alongside quadrant rank for comparison.
    """
    rows = []
    for h in (21, 63, 126):
        sub = df.dropna(subset=["quadrant_rank", f"fwd_ret_h{h}",
                                f"fwd_dd_h{h}", f"fwd_vol_h{h}"])
        if len(sub) < 50:
            continue
        for metric in ["ret", "dd", "vol"]:
            col = f"fwd_{metric}_h{h}"
            ic_quadrant = float(sub["quadrant_rank"].corr(sub[col], method="spearman"))
            ic_beta_mz = float(sub["beta_mz_h21"].corr(sub[col], method="spearman"))
            ic_beta_mkt = float(sub["beta_mkt"].corr(sub[col], method="spearman"))
            rows.append({
                "horizon": h,
                "metric": metric,
                "n": len(sub),
                "ic_quadrant_rank": ic_quadrant,
                "ic_beta_mz_continuous": ic_beta_mz,
                "ic_beta_mkt_continuous": ic_beta_mkt,
            })
    return pd.DataFrame(rows)


def write_summary(stats: pd.DataFrame, ic: pd.DataFrame, n_obs: int, out: Path) -> None:
    lines = ["# Regime Classifier — Economic Content Test", ""]
    lines.append(f"_Generated {pd.Timestamp.now().strftime('%Y-%m-%d')}, "
                 f"n={n_obs} (ticker × monthly snapshot) observations._")
    lines.append("")

    lines.append("## Hypothesized risk ordering (low → high):")
    lines.append("Q3 (genuinely calm) → Q4 (mega-cap buffer) → Q1 (stealth event-risk) → Q2 (idiosync + systematic)")
    lines.append("")

    lines.append("## Forward-outcome means by quadrant")
    if not stats.empty:
        for h in (21, 63, 126):
            lines.append(f"### H={h}d")
            sub = stats[stats["horizon"] == h]
            if sub.empty:
                continue
            lines.append("| Quadrant | n | Ret mean | Ret %neg | DD mean | DD p10 | Vol mean |")
            lines.append("|---|---|---|---|---|---|---|")
            for _, r in sub.iterrows():
                lines.append(f"| {r['quadrant']} | {int(r['n'])} | "
                             f"{r['ret_mean']:.3%} | {r['ret_pct_negative']:.0%} | "
                             f"{r['dd_mean']:.3%} | {r['dd_p10']:.3%} | "
                             f"{r['vol_mean']:.3f} |")
            lines.append("")

    lines.append("## IC of regime label vs forward outcomes")
    lines.append("- **ic_quadrant_rank**: Spearman rank correlation of quadrant ordering (0-3 by risk) vs realized")
    lines.append("- **ic_beta_mz_continuous**: rank correlation of raw β_mz vs realized")
    lines.append("- Expected sign: ret NEGATIVE (high regime risk → lower fwd ret), dd NEGATIVE (worse DD), vol POSITIVE (more vol)")
    lines.append("")
    lines.append("| Horizon | Metric | n | IC quadrant | IC β_mz | IC β_mkt |")
    lines.append("|---|---|---|---|---|---|")
    for _, r in ic.iterrows():
        lines.append(f"| H={int(r['horizon'])} | {r['metric']} | {int(r['n'])} | "
                     f"{r['ic_quadrant_rank']:+.4f} | {r['ic_beta_mz_continuous']:+.4f} | "
                     f"{r['ic_beta_mkt_continuous']:+.4f} |")
    lines.append("")

    lines.append("## Interpretation")
    lines.append("If the regime classifier carries economic content, you'd expect:")
    lines.append("- IC quadrant vs forward DD: **negative** (Q2 → worse DD than Q3)")
    lines.append("- IC quadrant vs forward vol: **positive** (Q2 → higher vol than Q3)")
    lines.append("- IC magnitude: 0.05–0.15 = real signal, 0.15+ = strong, comparable to factor models")
    lines.append("")
    lines.append("## Caveats")
    lines.append("- Trails are computed on full prediction history; not strictly OOS.")
    lines.append("- Quadrant boundaries (β=1.0) are arbitrary; many obs near boundary swap quadrants on small noise.")
    lines.append("- Sample size per quadrant uneven (Q3 typically dominates).")
    lines.append("- This tests REGIME LABEL signal, NOT vol-forecast signal. Different, complementary tests.")

    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    trails = load_trails()
    if trails.empty:
        print("[REGIME_SIGNAL] No trail files found.")
        return
    print(f"[REGIME_SIGNAL] Loaded {len(trails)} trail snapshots, "
          f"{trails['ticker'].nunique()} tickers")

    closes = load_closes()
    df = compute_forward_outcomes(trails, closes)
    if df.empty:
        print("[REGIME_SIGNAL] No forward outcomes computed.")
        return
    df = df.dropna(subset=["quadrant_rank"])
    print(f"[REGIME_SIGNAL] Forward-outcome table: {len(df)} rows")

    df_round = round_for_output(df, DECIMAL_PRECISION)
    df_round.to_csv(OUT / "regime_signal_observations.csv", index=False)

    stats = quadrant_distribution_stats(df)
    stats = round_for_output(stats, DECIMAL_PRECISION)
    stats.to_csv(OUT / "regime_signal_distribution.csv", index=False)
    print(f"[REGIME_SIGNAL] Wrote regime_signal_distribution.csv ({len(stats)} rows)")

    ic = compute_ic(df)
    ic = round_for_output(ic, DECIMAL_PRECISION)
    ic.to_csv(OUT / "regime_signal_ic.csv", index=False)
    print(f"[REGIME_SIGNAL] Wrote regime_signal_ic.csv ({len(ic)} rows)")

    write_summary(stats, ic, len(df), OUT / "regime_signal_summary.md")
    print()
    print("=" * 70)
    print("REGIME CLASSIFIER IC SUMMARY:")
    print("=" * 70)
    for h in (21, 63, 126):
        for metric in ["ret", "dd", "vol"]:
            row = ic[(ic["horizon"] == h) & (ic["metric"] == metric)]
            if not row.empty:
                r = row.iloc[0]
                print(f"H={h:3d} {metric:>3}: ic_quadrant={r['ic_quadrant_rank']:+.4f}  "
                      f"ic_beta_mz={r['ic_beta_mz_continuous']:+.4f}  n={int(r['n'])}")


if __name__ == "__main__":
    main()

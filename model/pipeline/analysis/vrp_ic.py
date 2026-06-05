"""
vrp_ic.py — Information Coefficient suite for VRP-derived signals.

The thesis claim: VRP (and its transformations) carries predictive information
about forward realized vol, returns, drawdowns. This is the central project
hypothesis — test it rigorously across the full 93-ticker corpus.

Predictors tested (8):
  vrp_raw           — vrp_wedge level (absolute)
  vrp_ewma          — 21-BD EWMA of vrp_wedge (smoothed)
  vrp_pct_own       — vrp_wedge percentile within own rolling 252-BD history
  vrp_ewma_pct_own  — vrp_ewma percentile within own rolling 252-BD history
  vrp_zscore_own    — vrp_wedge z-score within own rolling 252-BD
  vrp_slope5        — 5-BD linear slope of vrp_wedge
  vrp_ewma_slope5   — 5-BD slope of vrp_ewma (rate of change of smoothed)
  vrp_sign          — binary: vrp_wedge > 0

Per the bounded-ordinal principle (RESEARCH_TODO §6), VRP magnitude is
ticker-dependent (high-vol names structurally have higher VRP), so we test
BOTH raw and ticker-relative percentile/z-score versions.

Targets (forward outcomes, computed from CRSP closes):
  fwd_vol_h{21,63,126}     — annualized realized vol over forward h-BD window
  fwd_absret_h{21,63,126}  — absolute log return (vol-magnitude signal)
  fwd_ret_h{21,63,126}     — signed log return (directional)
  fwd_dd_h{21,63,126}      — max drawdown (negative log diff)

Outputs:
  results/validation/vrp_ic.csv             — full table per (pred × target × h)
  results/validation/vrp_ic_perticker.csv   — per-ticker IC distribution
  results/validation/vrp_ic_summary.md      — highlights + interpretation

Usage:
  python -m model.pipeline.analysis.vrp_ic
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from ..config import load_config
from ..data_loader import ParquetStore

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "model" / "pipeline" / "results"
OUT_DIR = RESULTS_DIR / "validation"

HORIZONS = (21, 63, 126)
METRICS = ("vol", "absret", "ret", "dd")
PREDICTORS = ("vrp_raw", "vrp_ewma", "vrp_pct_own", "vrp_ewma_pct_own",
              "vrp_zscore_own", "vrp_slope5", "vrp_ewma_slope5", "vrp_sign")

ROLLING_WINDOW = 252           # 1-year rolling window for own-history percentile/z
EWMA_HALFLIFE = 21             # 21-BD halflife for EWMA smoothing
MIN_OBS_FOR_IC_POOLED = 200
MIN_OBS_FOR_IC_PERTICKER = 100


# ═══════════════════════════════════════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════════════════════════════════════

def load_vrp_per_ticker() -> Dict[str, pd.DataFrame]:
    """Load vrp_wedge from per-ticker prediction files. One row per date.

    Pulls H=21 horizon rows for unique dates (vrp_wedge is a feature, not
    horizon-specific — same value across horizons for a given date).
    """
    out = {}
    for f in sorted(RESULTS_DIR.glob("predictions_*.csv")):
        ticker = f.stem.replace("predictions_", "")
        try:
            df = pd.read_csv(f, parse_dates=["date"],
                             usecols=["date", "vrp_wedge", "horizon"])
        except Exception:
            continue
        df = df[df["horizon"] == 21].drop(columns=["horizon"])
        df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        df = df.dropna(subset=["vrp_wedge"]).reset_index(drop=True)
        if len(df) < ROLLING_WINDOW + 50:
            continue
        out[ticker] = df
    return out


def load_closes() -> pd.DataFrame:
    """Load CRSP OHLCV closes pivoted as (date × ticker)."""
    dc, _, _ = load_config()
    s = ParquetStore(dc.base_dir)
    ohlcv = s.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    ohlcv = ohlcv.drop_duplicates(subset=["date", "ticker"], keep="last")
    return ohlcv.pivot(index="date", columns="ticker", values="prc").ffill()


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE ENGINEERING
# ═══════════════════════════════════════════════════════════════════════════════

def add_predictors(df: pd.DataFrame) -> pd.DataFrame:
    """Add all 8 VRP-derived predictors to a per-ticker dataframe."""
    df = df.copy().sort_values("date").reset_index(drop=True)
    v = df["vrp_wedge"]
    df["vrp_raw"] = v
    df["vrp_ewma"] = v.ewm(halflife=EWMA_HALFLIFE, adjust=False).mean()
    df["vrp_sign"] = (v > 0).astype(int)

    # Rolling own-history percentile (rank-based, value in [0,1])
    df["vrp_pct_own"] = v.rolling(ROLLING_WINDOW, min_periods=63).apply(
        lambda x: (x.rank().iloc[-1] - 1) / max(len(x) - 1, 1), raw=False)
    df["vrp_ewma_pct_own"] = df["vrp_ewma"].rolling(
        ROLLING_WINDOW, min_periods=63).apply(
        lambda x: (x.rank().iloc[-1] - 1) / max(len(x) - 1, 1), raw=False)

    # Rolling own-history z-score
    rmean = v.rolling(ROLLING_WINDOW, min_periods=63).mean()
    rstd  = v.rolling(ROLLING_WINDOW, min_periods=63).std()
    df["vrp_zscore_own"] = (v - rmean) / rstd.replace(0, np.nan)

    # 5-BD linear slope (just last-5 minus first-5 normalized by step count = 4)
    df["vrp_slope5"]      = v.diff(5) / 5.0
    df["vrp_ewma_slope5"] = df["vrp_ewma"].diff(5) / 5.0
    return df


def add_forward_outcomes(df: pd.DataFrame, ticker: str,
                          closes: pd.DataFrame) -> pd.DataFrame:
    """Compute forward outcomes by joining on ticker close series."""
    if ticker not in closes.columns:
        return df
    series = closes[ticker].dropna()
    if series.empty:
        return df

    df = df.copy().reset_index(drop=True)
    # Snapshot close per row via searchsorted into the closes series
    snap_close = np.full(len(df), np.nan)
    snap_idx   = np.full(len(df), -1, dtype=int)
    for i, d in enumerate(df["date"].values):
        d = pd.Timestamp(d)
        idx = series.index.searchsorted(d, side="right") - 1
        if 0 <= idx < len(series):
            snap_idx[i]   = idx
            snap_close[i] = series.iloc[idx]
    df["close"] = snap_close
    log_close = np.log(snap_close.astype(float))

    for h in HORIZONS:
        fwd_close = np.full(len(df), np.nan)
        fwd_min   = np.full(len(df), np.nan)
        fwd_vol   = np.full(len(df), np.nan)
        for i in range(len(df)):
            idx = snap_idx[i]
            if idx < 0:
                continue
            j_end = idx + h
            if j_end >= len(series):
                continue
            window = series.iloc[idx + 1: j_end + 1]
            if window.dropna().empty:
                continue
            fwd_close[i] = window.iloc[-1]
            fwd_min[i]   = window.min()
            log_returns  = np.log(window).diff().dropna().values
            if len(log_returns) > 5:
                fwd_vol[i] = float(np.std(log_returns) * np.sqrt(252))

        log_end = np.log(fwd_close)
        log_min = np.log(fwd_min)
        df[f"fwd_ret_h{h}"]    = log_end - log_close
        df[f"fwd_absret_h{h}"] = np.abs(log_end - log_close)
        df[f"fwd_dd_h{h}"]     = log_min - log_close
        df[f"fwd_vol_h{h}"]    = fwd_vol
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# IC COMPUTATION
# ═══════════════════════════════════════════════════════════════════════════════

def pooled_ic(df: pd.DataFrame) -> pd.DataFrame:
    """Pooled Spearman IC across all (ticker, date) observations."""
    rows = []
    for pred in PREDICTORS:
        for metric in METRICS:
            for h in HORIZONS:
                col = f"fwd_{metric}_h{h}"
                if col not in df.columns:
                    continue
                sub = df.dropna(subset=[pred, col])
                if len(sub) < MIN_OBS_FOR_IC_POOLED:
                    continue
                ic = float(sub[pred].corr(sub[col], method="spearman"))
                rows.append({"predictor": pred, "metric": metric, "horizon": h,
                             "n": len(sub), "ic_pooled": ic})
    return pd.DataFrame(rows)


def perticker_ic(df: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker Spearman IC: compute per ticker, then summarize across tickers."""
    rows = []
    for pred in PREDICTORS:
        for metric in METRICS:
            for h in HORIZONS:
                col = f"fwd_{metric}_h{h}"
                if col not in df.columns:
                    continue
                ics = []
                for tk, g in df.groupby("ticker"):
                    sub = g.dropna(subset=[pred, col])
                    if len(sub) < MIN_OBS_FOR_IC_PERTICKER:
                        continue
                    ic = float(sub[pred].corr(sub[col], method="spearman"))
                    if np.isfinite(ic):
                        ics.append(ic)
                if len(ics) < 10:
                    continue
                ics = np.asarray(ics)
                rows.append({
                    "predictor": pred, "metric": metric, "horizon": h,
                    "n_tickers": int(len(ics)),
                    "ic_median": float(np.median(ics)),
                    "ic_mean": float(np.mean(ics)),
                    "ic_iqr_lo": float(np.percentile(ics, 25)),
                    "ic_iqr_hi": float(np.percentile(ics, 75)),
                    "frac_same_sign_005": float(np.mean(
                        np.sign(ics) == np.sign(np.median(ics))) if np.median(ics) != 0 else np.nan),
                    "frac_abs_above_010": float(np.mean(np.abs(ics) > 0.10)),
                })
    return pd.DataFrame(rows)


def quintile_lift(df: pd.DataFrame, predictor: str,
                  target: str, n_bins: int = 5) -> Dict:
    """Top-vs-bottom quintile spread on target. Higher mean target in top quintile
    of predictor = positive directional signal (sign depends on metric).
    """
    sub = df.dropna(subset=[predictor, target])
    if len(sub) < MIN_OBS_FOR_IC_POOLED:
        return {"q1_mean": np.nan, "q5_mean": np.nan, "spread": np.nan, "n": 0}
    try:
        sub = sub.assign(qtl=pd.qcut(sub[predictor], q=n_bins,
                                     labels=False, duplicates="drop"))
    except ValueError:
        return {"q1_mean": np.nan, "q5_mean": np.nan, "spread": np.nan, "n": 0}
    q1 = sub[sub["qtl"] == 0][target].mean()
    q5 = sub[sub["qtl"] == n_bins - 1][target].mean()
    return {"q1_mean": float(q1), "q5_mean": float(q5),
            "spread": float(q5 - q1), "n": len(sub)}


# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

def write_summary(pooled: pd.DataFrame, perticker: pd.DataFrame,
                  lifts: pd.DataFrame, out: Path) -> None:
    lines = ["# VRP Information Coefficient Suite", "",
             "Tests whether VRP-derived signals predict forward outcomes. The",
             "central thesis of the project — does VRP carry forward-looking",
             "information?",
             "",
             "## Sign expectations",
             "- `vol`: higher VRP-fear/elevation → higher forward vol → POSITIVE IC",
             "- `absret`: same intuition → POSITIVE IC",
             "- `ret`: contrarian/mean-revert literature → POSITIVE IC at long horizons",
             "  (high VRP = fear priced = subsequent rally)",
             "- `dd`: higher fear → worse forward drawdown → NEGATIVE IC",
             "",
             "## Pooled IC (all tickers × dates concatenated)", ""]

    # Pivot pooled to readable table per metric
    for metric in METRICS:
        sub = pooled[pooled["metric"] == metric]
        if sub.empty:
            continue
        piv = sub.pivot_table(index="predictor", columns="horizon",
                              values="ic_pooled").reset_index()
        piv.columns = ["predictor"] + [f"h{h}" for h in piv.columns[1:]]
        lines += [f"### Forward {metric.upper()}", ""]
        # Find best row per metric (max |IC| at h=21, the cleanest horizon)
        if "h21" in piv.columns:
            best_idx = piv["h21"].abs().idxmax()
            best_pred = piv.loc[best_idx, "predictor"]
            lines.append(f"**Best at H=21:** `{best_pred}` (IC={piv.loc[best_idx, 'h21']:+.3f})")
            lines.append("")
        header = "| predictor | " + " | ".join(f"h{h}" for h in HORIZONS) + " |"
        sep    = "|---|" + "|".join(["---"] * len(HORIZONS)) + "|"
        lines += [header, sep]
        for _, r in piv.iterrows():
            cells = [r["predictor"]] + [f"{r.get(f'h{h}', float('nan')):+.3f}"
                                        for h in HORIZONS]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    lines += ["## Per-ticker IC distribution (median across tickers)",
              "",
              "Pooled IC can be inflated by between-ticker variance; per-ticker",
              "median is the strict test. `frac_abs_above_010` = fraction of",
              "tickers where |IC| > 0.10 (rule-of-thumb actionable threshold).",
              ""]
    for metric in METRICS:
        sub = perticker[perticker["metric"] == metric]
        if sub.empty:
            continue
        lines += [f"### Forward {metric.upper()}", ""]
        header = ("| predictor | h | n_tickers | ic_median | ic_mean | "
                  "iqr_lo | iqr_hi | frac>0.10 |")
        sep    = "|---|---|---|---|---|---|---|---|"
        lines += [header, sep]
        for _, r in sub.iterrows():
            lines.append(
                f"| {r['predictor']} | {r['horizon']} | "
                f"{int(r['n_tickers'])} | {r['ic_median']:+.3f} | "
                f"{r['ic_mean']:+.3f} | {r['ic_iqr_lo']:+.3f} | "
                f"{r['ic_iqr_hi']:+.3f} | {r['frac_abs_above_010']:.2f} |")
        lines.append("")

    if not lifts.empty:
        lines += ["## Top-vs-bottom quintile spread on forward vol (H=21)", "",
                  "Q5 = highest predictor values, Q1 = lowest. Spread > 0 = top",
                  "quintile of predictor has higher forward vol than bottom.",
                  ""]
        header = "| predictor | n | Q1 mean | Q5 mean | spread |"
        sep    = "|---|---|---|---|---|"
        lines += [header, sep]
        for _, r in lifts.iterrows():
            lines.append(
                f"| {r['predictor']} | {int(r['n'])} | "
                f"{r['q1_mean']:.4f} | {r['q5_mean']:.4f} | "
                f"{r['spread']:+.4f} |")
        lines.append("")

    lines += ["## How to read",
              "",
              "- A predictor has **actionable signal** if pooled IC is in the",
              "  expected sign AND per-ticker median IC is the same sign AND",
              "  `frac>0.10` ≥ 0.3 (at least 30% of tickers show |IC| > 0.10).",
              "- If `vrp_pct_own` beats `vrp_raw`, the ordinal/relative framing",
              "  works for VRP (validating the bounded principle from §6 holds",
              "  here as expected — VRP is vol-magnitude-units).",
              "- If `vrp_ewma_slope5` shows positive IC for forward vol, the",
              "  prior 6-ticker finding that VRP_ewma slope is predictive",
              "  generalizes to the 93-ticker corpus."]
    out.write_text("\n".join(lines), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[VRP_IC] Loading per-ticker predictions...")
    per_t = load_vrp_per_ticker()
    if not per_t:
        print("[VRP_IC] No predictions found.")
        return 1
    print(f"  {len(per_t)} tickers with sufficient history")

    print("[VRP_IC] Adding predictor features per ticker...")
    for tk in per_t:
        per_t[tk] = add_predictors(per_t[tk])

    print("[VRP_IC] Loading closes for forward outcomes...")
    closes = load_closes()

    print("[VRP_IC] Computing forward outcomes per ticker...")
    pieces = []
    for i, tk in enumerate(sorted(per_t), 1):
        df = add_forward_outcomes(per_t[tk], tk, closes)
        df["ticker"] = tk
        pieces.append(df)
        if i % 20 == 0:
            print(f"  {i}/{len(per_t)} tickers done")
    full = pd.concat(pieces, ignore_index=True)
    print(f"[VRP_IC] {len(full):,} total (ticker, date) observations")

    print("[VRP_IC] Computing pooled IC...")
    pooled = pooled_ic(full)
    pooled_path = OUT_DIR / "vrp_ic.csv"
    pooled.to_csv(pooled_path, index=False)

    print("[VRP_IC] Computing per-ticker IC distribution...")
    perticker = perticker_ic(full)
    perticker_path = OUT_DIR / "vrp_ic_perticker.csv"
    perticker.to_csv(perticker_path, index=False)

    print("[VRP_IC] Computing top-vs-bottom quintile lifts on fwd_vol_h21...")
    lifts = []
    for pred in PREDICTORS:
        d = quintile_lift(full, pred, "fwd_vol_h21")
        d["predictor"] = pred
        lifts.append(d)
    lifts_df = pd.DataFrame(lifts)[["predictor", "n", "q1_mean",
                                    "q5_mean", "spread"]]

    md_path = OUT_DIR / "vrp_ic_summary.md"
    write_summary(pooled, perticker, lifts_df, md_path)

    print(f"\n[VRP_IC] Wrote {pooled_path}")
    print(f"[VRP_IC] Wrote {perticker_path}")
    print(f"[VRP_IC] Wrote {md_path}")

    print("\n=== POOLED IC — forward VOL (the cleanest target) ===")
    sub = pooled[pooled.metric == "vol"]
    piv = sub.pivot_table(index="predictor", columns="horizon",
                          values="ic_pooled")
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(piv.to_string())

    print("\n=== PER-TICKER MEDIAN IC — forward VOL, h=21 ===")
    sub = perticker[(perticker.metric == "vol") & (perticker.horizon == 21)]
    out = sub[["predictor", "n_tickers", "ic_median", "ic_mean",
               "frac_abs_above_010"]].sort_values("ic_median", ascending=False)
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(out.to_string(index=False))

    print("\n=== QUINTILE LIFT on forward vol (H=21) ===")
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.4f}"):
        print(lifts_df.to_string(index=False))

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

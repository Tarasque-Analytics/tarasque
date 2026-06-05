"""
aggregate_beta_signal.py — Does the slope of the universe-aggregate β_mz
                            predict market vol shocks?

Hypothesis (Leo): when the corpus-mean β_mz declines (calm regime → model
over-predicts vol across the universe) and then the slope SIGN-FLIPS positive
(β_mz starts rising → model under-predicting → vol is regime-shifting up),
that pivot tends to precede market-wide vol shocks.

If true: this is a corpus-level early warning that doesn't require any
per-ticker pattern matching. Pure aggregated metadata of model calibration.

Method
------
1. Load all per-ticker `regime_trail/*_trail.csv` (24 monthly β_mz snapshots each)
2. Aggregate per snapshot date: mean β_mz across universe
3. Compute 3-month rolling SLOPE of aggregate β_mz
4. Mark sign-change events (slope flips negative → positive, or vice versa)
5. For each sign-change, look at forward SPY realized vol over next 21/42/63 BD
6. Compare to baseline (forward SPY vol on random non-event dates)
7. Report: are sign-change dates followed by elevated SPY vol vs baseline?

Sample size caveat: only 24 monthly snapshots per ticker → ~20 aggregate dates
after rolling-window slope → maybe 3-6 sign-change events. Small N. If pattern
looks suggestive, re-run at higher cadence (weekly β_mz recomputation).

Outputs:
  results/validation/aggregate_beta_signal.csv
  results/validation/aggregate_beta_signal_summary.md
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import load_config
from ..data_loader import ParquetStore

REPO_ROOT = Path(__file__).resolve().parents[3]
TRAILS_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "regime_trail"
OUT_DIR    = REPO_ROOT / "model" / "pipeline" / "results" / "validation"

SLOPE_WINDOW = 3       # 3-month rolling slope
FWD_HORIZONS = (21, 42, 63)


def load_aggregate_beta() -> pd.DataFrame:
    """Load all trail CSVs, aggregate per snapshot date."""
    dfs = []
    for f in sorted(TRAILS_DIR.glob("*_trail.csv")):
        ticker = f.stem.replace("_trail", "")
        df = pd.read_csv(f, parse_dates=["asof"])
        df["ticker"] = ticker
        dfs.append(df)
    if not dfs:
        return pd.DataFrame()
    trails = pd.concat(dfs, ignore_index=True)
    print(f"[AGG_BETA] Loaded {len(trails)} snapshots from {trails.ticker.nunique()} tickers")
    print(f"[AGG_BETA] Date range: {trails['asof'].min().date()} to {trails['asof'].max().date()}")

    agg = trails.groupby("asof").agg(
        mean_bmz=("beta_mz_h21", "mean"),
        median_bmz=("beta_mz_h21", "median"),
        std_bmz=("beta_mz_h21", "std"),
        n_tickers=("beta_mz_h21", "count"),
    ).reset_index().sort_values("asof").reset_index(drop=True)
    return agg


def add_slope_and_signs(agg: pd.DataFrame, window: int = SLOPE_WINDOW) -> pd.DataFrame:
    """3-month rolling slope of mean_bmz + sign-change markers."""
    def _slope(s: pd.Series) -> float:
        if s.isna().any() or len(s) < window:
            return np.nan
        x = np.arange(len(s), dtype=float)
        return float(np.polyfit(x, s.values, 1)[0])

    agg = agg.copy()
    agg["slope"]   = agg["mean_bmz"].rolling(window, min_periods=window).apply(_slope, raw=False)
    agg["sign"]    = np.sign(agg["slope"])
    agg["sign_lag"] = agg["sign"].shift(1)
    agg["sign_change"] = (
        (agg["sign"] != agg["sign_lag"])
        & agg["sign"].notna() & agg["sign_lag"].notna()
    )
    agg["direction"] = agg.apply(
        lambda r: "down→up" if (r["sign_lag"] < 0 and r["sign"] > 0)
                  else ("up→down" if (r["sign_lag"] > 0 and r["sign"] < 0)
                        else ""),
        axis=1
    )
    return agg


def load_spy_vol() -> pd.Series:
    """SPY rolling 21d realized vol (annualized) from CRSP parquet cache."""
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    ohlcv = store.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    spy = ohlcv[ohlcv["ticker"] == "SPY"].drop_duplicates(subset=["date"], keep="last")
    if spy.empty:
        # Fallback: use mean of universe as "market" proxy
        print("[AGG_BETA] WARNING: SPY not in cache. Using universe-mean log returns as proxy.")
        closes = ohlcv.pivot_table(index="date", columns="ticker",
                                    values="prc", aggfunc="last").ffill()
        mkt = closes.mean(axis=1)
    else:
        mkt = spy.set_index("date")["prc"].sort_index()
    log_ret = np.log(mkt).diff().dropna()
    vol_21d = log_ret.rolling(21).std() * np.sqrt(252)
    return vol_21d.dropna()


def forward_vol_around_event(spy_vol: pd.Series, event_date: pd.Timestamp,
                              horizon_bd: int) -> dict:
    """For an event date, summarize SPY vol over the next `horizon_bd` BD."""
    # Find next trading day on or after event_date in spy_vol index
    idx = spy_vol.index.searchsorted(event_date, side="left")
    if idx >= len(spy_vol):
        return {"max": np.nan, "mean": np.nan, "p75": np.nan, "n_obs": 0}
    end_idx = min(idx + horizon_bd, len(spy_vol))
    window = spy_vol.iloc[idx:end_idx]
    if window.empty:
        return {"max": np.nan, "mean": np.nan, "p75": np.nan, "n_obs": 0}
    return {"max": float(window.max()), "mean": float(window.mean()),
            "p75": float(window.quantile(0.75)), "n_obs": len(window)}


def baseline_vol_distribution(spy_vol: pd.Series,
                              non_event_dates: list,
                              horizon_bd: int) -> dict:
    """Forward vol stats on non-event dates (baseline for comparison)."""
    samples = []
    for d in non_event_dates:
        idx = spy_vol.index.searchsorted(d, side="left")
        if idx + horizon_bd >= len(spy_vol):
            continue
        window = spy_vol.iloc[idx:idx + horizon_bd]
        if not window.empty:
            samples.append(window.max())
    if not samples:
        return {"baseline_max_mean": np.nan, "baseline_max_p50": np.nan,
                "baseline_max_p75": np.nan, "n_samples": 0}
    arr = np.asarray(samples, dtype=float)
    return {"baseline_max_mean": float(np.nanmean(arr)),
            "baseline_max_p50": float(np.nanpercentile(arr, 50)),
            "baseline_max_p75": float(np.nanpercentile(arr, 75)),
            "n_samples": len(samples)}


def write_summary(agg: pd.DataFrame, event_rows: list, baselines: dict,
                  out: Path) -> None:
    lines = ["# Aggregate β_mz Slope Sign-Change Signal Test", "",
             "Hypothesis: when universe-mean β_mz slope flips sign (especially",
             "down→up), market vol shocks tend to follow.", "",
             "## Aggregate β_mz time series", "",
             f"Snapshots: {len(agg)} monthly | tickers contributing: {agg['n_tickers'].max()}",
             "",
             "| asof | mean_bmz | median_bmz | std | slope (3mo) | sign change |",
             "|---|---|---|---|---|---|"]
    for _, r in agg.iterrows():
        sc = r["direction"] if r["sign_change"] else ""
        slope_str = f"{r['slope']:+.4f}" if pd.notna(r["slope"]) else "—"
        lines.append(f"| {r['asof'].date()} | {r['mean_bmz']:.3f} | "
                     f"{r['median_bmz']:.3f} | {r['std_bmz']:.3f} | "
                     f"{slope_str} | {sc} |")
    lines.append("")

    lines += ["## Forward SPY vol after each sign-change event", "",
              "| event date | direction | h=21 max | h=42 max | h=63 max |",
              "|---|---|---|---|---|"]
    for r in event_rows:
        lines.append(
            f"| {r['event_date']} | {r['direction']} | "
            f"{r['h21_max']:.3f} | {r['h42_max']:.3f} | {r['h63_max']:.3f} |")
    lines.append("")

    lines += ["## Baseline forward SPY vol (non-event dates)", ""]
    for h, b in baselines.items():
        lines.append(f"- **h={h}d**: baseline max-vol mean = {b['baseline_max_mean']:.3f}, "
                     f"p50 = {b['baseline_max_p50']:.3f}, p75 = {b['baseline_max_p75']:.3f} "
                     f"(n={b['n_samples']})")
    lines += ["", "## How to read",
              "",
              "- If h21/h42/h63 max for DOWN→UP events systematically EXCEED the baseline",
              "  p75, the signal has predictive value.",
              "- If event-day vol distribution looks indistinguishable from baseline, the",
              "  pattern is coincidence at this sample size.",
              "- Small-N caveat: only ~24 monthly snapshots means ~3-6 sign-change events.",
              "  Pattern can SUGGEST but not PROVE; higher-cadence recomputation needed",
              "  for statistical confidence.", ""]
    out.write_text("\n".join(lines), encoding="utf-8")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[AGG_BETA] Loading aggregate β_mz time series...")
    agg = load_aggregate_beta()
    if agg.empty:
        print("[AGG_BETA] No trails found. Run regime_trail.py first.")
        return 1

    print(f"[AGG_BETA] Computing {SLOPE_WINDOW}-month rolling slope + sign-change markers...")
    agg = add_slope_and_signs(agg, window=SLOPE_WINDOW)

    # Save raw aggregate
    agg.to_csv(OUT_DIR / "aggregate_beta_signal.csv", index=False)

    print("\n=== Aggregate β_mz with slope + sign-change markers ===")
    cols = ["asof", "mean_bmz", "median_bmz", "slope", "direction"]
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.4f}"):
        print(agg[cols].to_string(index=False))

    # Sign-change events
    events = agg[agg["sign_change"]].copy()
    print(f"\n[AGG_BETA] Sign-change events: {len(events)}")
    if events.empty:
        print("[AGG_BETA] No sign changes in available data.")
        return 0

    print("[AGG_BETA] Loading SPY rolling vol...")
    spy_vol = load_spy_vol()

    # Per-event forward vol
    event_rows = []
    for _, ev in events.iterrows():
        row = {"event_date": ev["asof"].date().isoformat(),
               "direction": ev["direction"]}
        for h in FWD_HORIZONS:
            stats = forward_vol_around_event(spy_vol, ev["asof"], h)
            row[f"h{h}_max"] = stats["max"]
            row[f"h{h}_mean"] = stats["mean"]
        event_rows.append(row)

    event_df = pd.DataFrame(event_rows)
    print("\n=== Forward SPY vol after each sign-change ===")
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:.3f}"):
        print(event_df.to_string(index=False))

    # Baseline: non-event dates (use all aggregate dates without sign changes)
    non_event = agg[~agg["sign_change"] & agg["slope"].notna()]["asof"].tolist()
    baselines = {h: baseline_vol_distribution(spy_vol, non_event, h)
                 for h in FWD_HORIZONS}

    print("\n=== Baseline forward SPY vol (non-event dates) ===")
    for h, b in baselines.items():
        print(f"  h={h:2d}d: baseline max mean={b['baseline_max_mean']:.3f}, "
              f"p75={b['baseline_max_p75']:.3f} (n={b['n_samples']})")

    # Simple verdict on most common direction
    down_up = event_df[event_df["direction"] == "down→up"]
    if not down_up.empty:
        b = baselines[21]
        h21_mean = down_up["h21_max"].mean()
        lift = h21_mean / b["baseline_max_mean"] if b["baseline_max_mean"] else np.nan
        print(f"\n[AGG_BETA] DOWN→UP events (n={len(down_up)}):")
        print(f"  forward h=21d max-vol mean: {h21_mean:.3f}")
        print(f"  baseline max-vol mean:      {b['baseline_max_mean']:.3f}")
        print(f"  ratio (lift): {lift:.2f}x")

    write_summary(agg, event_rows, baselines,
                  OUT_DIR / "aggregate_beta_signal_summary.md")
    print(f"\n[AGG_BETA] Wrote results to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

"""
aggregate_beta_weekly.py — Weekly-cadence aggregate beta_mz test.

Higher-resolution version of aggregate_beta_signal.py. Computes beta_mz per ticker
at WEEKLY (Friday) snapshots instead of monthly, giving ~5x more data points
to test whether universe-aggregate beta_mz slope sign-changes precede vol shocks.

Uses the same OLS-on-rolling-252-BD-of-WFA-predictions methodology as
regime_trail.py:beta_mz_at(). Just at finer cadence.

Outputs:
  results/validation/aggregate_beta_weekly.csv
  results/validation/aggregate_beta_weekly_summary.md
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import load_config
from ..data_loader import ParquetStore

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "model" / "pipeline" / "results"
OUT_DIR = RESULTS_DIR / "validation"

ROLLING_BD = 252            # OLS window for each beta_mz fit
SLOPE_WINDOW_WEEKS = 12     # 12-week rolling slope of aggregate beta_mz (~quarterly)
FWD_HORIZONS = (21, 42, 63)


def beta_mz_at(preds_h21: pd.DataFrame, asof: pd.Timestamp) -> tuple:
    """OLS log-log MZ regression of y_true on y_pred over preceding 252-BD window."""
    sub = preds_h21[preds_h21["date"] <= asof].sort_values("date").tail(ROLLING_BD)
    sub = sub.dropna(subset=["y_true", "y_pred"])
    if len(sub) < 60:
        return (np.nan, 0)
    yt = np.log(np.clip(sub["y_true"], 1e-6, None))
    yp = np.log(np.clip(sub["y_pred"], 1e-6, None))
    var = float(yp.var(ddof=1))
    if var == 0 or not np.isfinite(var):
        return (np.nan, len(sub))
    cov = float(np.cov(yt, yp, ddof=1)[0, 1])
    return (cov / var, len(sub))


def compute_weekly_beta_per_ticker() -> pd.DataFrame:
    """Per ticker, compute beta_mz at each Friday across the prediction window."""
    rows = []
    for f in sorted(RESULTS_DIR.glob("predictions_*.csv")):
        ticker = f.stem.replace("predictions_", "")
        try:
            df = pd.read_csv(f, parse_dates=["date"],
                             usecols=["date", "y_true", "y_pred", "horizon"])
        except Exception:
            continue
        h21 = df[df["horizon"] == 21].drop(columns=["horizon"])
        if h21.empty or len(h21) < ROLLING_BD + 20:
            continue
        first_valid = h21["date"].min() + pd.tseries.offsets.BDay(ROLLING_BD)
        last_valid  = h21["date"].max()
        # Friday snapshots
        fridays = pd.date_range(first_valid, last_valid, freq="W-FRI")
        for fr in fridays:
            beta, n = beta_mz_at(h21, fr)
            if np.isfinite(beta):
                rows.append({"ticker": ticker, "asof": fr, "beta_mz": beta, "n_obs": n})
    return pd.DataFrame(rows)


def aggregate(weekly: pd.DataFrame) -> pd.DataFrame:
    return weekly.groupby("asof").agg(
        mean_bmz=("beta_mz", "mean"),
        median_bmz=("beta_mz", "median"),
        std_bmz=("beta_mz", "std"),
        n_tickers=("beta_mz", "count"),
    ).reset_index().sort_values("asof").reset_index(drop=True)


def add_slope_and_signs(agg: pd.DataFrame, window: int = SLOPE_WINDOW_WEEKS) -> pd.DataFrame:
    def _slope(s):
        if s.isna().any() or len(s) < window:
            return np.nan
        x = np.arange(len(s), dtype=float)
        return float(np.polyfit(x, s.values, 1)[0])

    agg = agg.copy()
    agg["slope"]    = agg["mean_bmz"].rolling(window, min_periods=window).apply(_slope, raw=False)
    agg["sign"]     = np.sign(agg["slope"])
    agg["sign_lag"] = agg["sign"].shift(1)
    agg["sign_change"] = (
        (agg["sign"] != agg["sign_lag"])
        & agg["sign"].notna() & agg["sign_lag"].notna()
    )
    agg["direction"] = agg.apply(
        lambda r: "down->up" if (r["sign_lag"] < 0 and r["sign"] > 0)
                  else ("up->down" if (r["sign_lag"] > 0 and r["sign"] < 0)
                        else ""),
        axis=1
    )
    return agg


def load_spy_vol() -> pd.Series:
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    ohlcv = store.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    spy = ohlcv[ohlcv["ticker"] == "SPY"].drop_duplicates(subset=["date"], keep="last")
    if spy.empty:
        # Universe mean fallback
        closes = ohlcv.pivot_table(index="date", columns="ticker",
                                    values="prc", aggfunc="last").ffill()
        mkt = closes.mean(axis=1)
    else:
        mkt = spy.set_index("date")["prc"].sort_index()
    log_ret = np.log(mkt).diff().dropna()
    return (log_ret.rolling(21).std() * np.sqrt(252)).dropna()


def fwd_vol(spy_vol: pd.Series, d: pd.Timestamp, h: int) -> float:
    idx = spy_vol.index.searchsorted(d, side="left")
    if idx + h >= len(spy_vol):
        return np.nan
    return float(spy_vol.iloc[idx:idx + h].max())


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[AGG_BETA_W] Computing per-ticker weekly beta_mz...")
    weekly = compute_weekly_beta_per_ticker()
    if weekly.empty:
        print("[AGG_BETA_W] No predictions found.")
        return 1
    print(f"  {len(weekly):,} (ticker, week) beta_mz observations from "
          f"{weekly['ticker'].nunique()} tickers")
    print(f"  Date range: {weekly['asof'].min().date()} -> {weekly['asof'].max().date()}")

    print("[AGG_BETA_W] Aggregating per snapshot week...")
    agg = aggregate(weekly)
    print(f"  {len(agg)} weekly snapshots (universe-wide aggregate)")

    print(f"[AGG_BETA_W] Computing {SLOPE_WINDOW_WEEKS}-week slope + sign-change markers...")
    agg = add_slope_and_signs(agg, window=SLOPE_WINDOW_WEEKS)
    agg.to_csv(OUT_DIR / "aggregate_beta_weekly.csv", index=False)

    n_changes = int(agg["sign_change"].sum())
    n_down_up = int(((agg["sign_lag"] < 0) & (agg["sign"] > 0)).sum())
    n_up_down = int(((agg["sign_lag"] > 0) & (agg["sign"] < 0)).sum())
    print(f"  Sign changes: {n_changes} total ({n_down_up} down->up, {n_up_down} up->down)")

    print("[AGG_BETA_W] Loading SPY vol...")
    spy_vol = load_spy_vol()

    events = agg[agg["sign_change"]].copy()
    event_rows = []
    for _, ev in events.iterrows():
        row = {"event_date": ev["asof"].date().isoformat(),
               "direction": ev["direction"]}
        for h in FWD_HORIZONS:
            row[f"h{h}_max"] = fwd_vol(spy_vol, ev["asof"], h)
        event_rows.append(row)
    event_df = pd.DataFrame(event_rows)

    # Baselines from non-event dates
    non_event_dates = agg[~agg["sign_change"] & agg["slope"].notna()]["asof"].tolist()
    baselines = {}
    for h in FWD_HORIZONS:
        samples = [fwd_vol(spy_vol, d, h) for d in non_event_dates]
        samples = [s for s in samples if np.isfinite(s)]
        baselines[h] = {
            "mean": float(np.mean(samples)) if samples else np.nan,
            "p50": float(np.percentile(samples, 50)) if samples else np.nan,
            "p75": float(np.percentile(samples, 75)) if samples else np.nan,
            "n": len(samples),
        }

    print("\n=== Sign-change events (weekly cadence) ===")
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:.3f}"):
        print(event_df.to_string(index=False))

    print("\n=== Baseline forward SPY vol (non-event weekly dates) ===")
    for h, b in baselines.items():
        print(f"  h={h:2d}d: max-vol mean={b['mean']:.3f}, p50={b['p50']:.3f}, "
              f"p75={b['p75']:.3f}, n={b['n']}")

    print("\n=== Lift summary by direction ===")
    for direction in ("down->up", "up->down"):
        sub = event_df[event_df["direction"] == direction]
        if sub.empty:
            continue
        for h in FWD_HORIZONS:
            ev_mean = float(sub[f"h{h}_max"].mean())
            base = baselines[h]["mean"]
            lift = ev_mean / base if base and np.isfinite(base) and base > 0 else np.nan
            print(f"  {direction:10s} h={h:2d}d: event max-vol mean={ev_mean:.3f}  "
                  f"vs baseline {base:.3f}  -> lift {lift:.2f}x  (n={len(sub)})")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

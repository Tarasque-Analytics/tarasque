"""
beta_mz_deep_dive.py — Comprehensive validation of the universe-aggregate β_mz
                       signal beyond the initial single-cadence test.

Five analyses:

  1. ROBUSTNESS: signal performance across smoothing windows {4, 8, 12, 24} weeks.
     If signal works at multiple windows → robust regime detector. If only at
     12-week → likely overfit to that specific parameter.

  2. LEAD TIME: for each historical down→up event, what's the gap (in BD) between
     the signal date and the subsequent SPY vol peak? Actionability test.

  3. FALSE POSITIVES: among 18 historical down→up events, what fraction preceded
     a defined "real shock" (SPY vol > P90 of 252-BD rolling baseline within next
     42 BD)? Hit rate by direction.

  4. LEVEL vs SLOPE: is absolute β_mz level informative on top of slope direction?
     IC of agg_bmz level vs forward SPY vol, controlling for slope.

  5. CURRENT STATE: where are we now? What does the signal say about the present?

Outputs:
  results/validation/beta_mz_deep_dive.csv         — robustness across windows
  results/validation/beta_mz_event_table.csv       — every signal event + lead time + hit
  results/validation/beta_mz_deep_dive_summary.md  — written analysis
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

ROLLING_BD_BMZ = 252       # window for per-ticker MZ regression
SLOPE_WINDOWS = [4, 8, 12, 24]  # in WEEKS
FWD_HORIZONS = (21, 42, 63)
SHOCK_DEFINITION_HORIZON = 42  # BD over which we look for "shock" after a signal
SHOCK_PCTILE = 0.90             # SPY vol > P90 of trailing 252-BD = "shock"


# ============================================================================
# 1. RECONSTRUCT WEEKLY β_mz TIME SERIES (same logic as aggregate_beta_weekly.py)
# ============================================================================

def beta_mz_at(preds_h21: pd.DataFrame, asof: pd.Timestamp) -> tuple:
    sub = preds_h21[preds_h21["date"] <= asof].sort_values("date").tail(ROLLING_BD_BMZ)
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


def compute_weekly_aggregate() -> pd.DataFrame:
    """Per snapshot Friday: universe-mean β_mz across all tickers."""
    rows = []
    for f in sorted(RESULTS_DIR.glob("predictions_*.csv")):
        ticker = f.stem.replace("predictions_", "")
        try:
            df = pd.read_csv(f, parse_dates=["date"],
                             usecols=["date", "y_true", "y_pred", "horizon"])
        except Exception:
            continue
        h21 = df[df["horizon"] == 21].drop(columns=["horizon"])
        if h21.empty or len(h21) < ROLLING_BD_BMZ + 20:
            continue
        first_valid = h21["date"].min() + pd.tseries.offsets.BDay(ROLLING_BD_BMZ)
        last_valid  = h21["date"].max()
        for fr in pd.date_range(first_valid, last_valid, freq="W-FRI"):
            beta, _ = beta_mz_at(h21, fr)
            if np.isfinite(beta):
                rows.append({"ticker": ticker, "asof": fr, "beta_mz": beta})
    if not rows:
        return pd.DataFrame()
    weekly = pd.DataFrame(rows)
    return weekly.groupby("asof").agg(
        mean_bmz=("beta_mz", "mean"),
        median_bmz=("beta_mz", "median"),
        std_bmz=("beta_mz", "std"),
        n_tickers=("beta_mz", "count"),
    ).reset_index().sort_values("asof").reset_index(drop=True)


# ============================================================================
# 2. SPY ROLLING VOL FOR FORWARD-LOOKING METRICS
# ============================================================================

def load_spy_vol() -> pd.Series:
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    ohlcv = store.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    spy = ohlcv[ohlcv["ticker"] == "SPY"].drop_duplicates(subset=["date"], keep="last")
    if spy.empty:
        closes = ohlcv.pivot_table(index="date", columns="ticker",
                                    values="prc", aggfunc="last").ffill()
        mkt = closes.mean(axis=1)
    else:
        mkt = spy.set_index("date")["prc"].sort_index()
    log_ret = np.log(mkt).diff().dropna()
    return (log_ret.rolling(21).std() * np.sqrt(252)).dropna()


# ============================================================================
# 3. SLOPE + SIGN CHANGE DETECTION AT VARIABLE WINDOWS
# ============================================================================

def add_slope_signs(agg: pd.DataFrame, window_weeks: int) -> pd.DataFrame:
    def _slope(s):
        if s.isna().any() or len(s) < window_weeks:
            return np.nan
        x = np.arange(len(s), dtype=float)
        return float(np.polyfit(x, s.values, 1)[0])

    out = agg.copy()
    out[f"slope_w{window_weeks}"] = out["mean_bmz"].rolling(
        window_weeks, min_periods=window_weeks).apply(_slope, raw=False)
    out[f"sign_w{window_weeks}"] = np.sign(out[f"slope_w{window_weeks}"])
    out[f"sign_lag_w{window_weeks}"] = out[f"sign_w{window_weeks}"].shift(1)
    out[f"sign_change_w{window_weeks}"] = (
        (out[f"sign_w{window_weeks}"] != out[f"sign_lag_w{window_weeks}"])
        & out[f"sign_w{window_weeks}"].notna()
        & out[f"sign_lag_w{window_weeks}"].notna()
    )
    return out


# ============================================================================
# 4. EVENT SUMMARIES — lead time, shock detection
# ============================================================================

def shock_threshold_at(spy_vol: pd.Series, d: pd.Timestamp) -> float:
    """Rolling P90 of SPY vol over trailing 252 BD as of date d. Defines 'shock'."""
    idx = spy_vol.index.searchsorted(d, side="right") - 1
    if idx < 252:
        return np.nan
    window = spy_vol.iloc[max(0, idx - 252):idx + 1]
    return float(window.quantile(SHOCK_PCTILE))


def did_shock_happen(spy_vol: pd.Series, event_date: pd.Timestamp,
                     horizon: int, threshold: float) -> dict:
    """Forward look: did SPY vol exceed threshold within next h BD?
    If yes, return lead_time (BD from event to first crossing) and peak."""
    idx = spy_vol.index.searchsorted(event_date, side="left")
    end_idx = min(idx + horizon, len(spy_vol))
    if end_idx <= idx:
        return {"shock": False, "lead_bd": np.nan, "peak": np.nan}
    window = spy_vol.iloc[idx:end_idx]
    over = window[window > threshold]
    if over.empty:
        return {"shock": False, "lead_bd": np.nan, "peak": float(window.max()),
                "threshold": threshold}
    first_cross_idx = window.index.get_loc(over.index[0])
    return {"shock": True, "lead_bd": int(first_cross_idx),
            "peak": float(window.max()), "threshold": threshold}


# ============================================================================
# MAIN
# ============================================================================

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[BMZ_DEEP] Building weekly aggregate β_mz...")
    agg = compute_weekly_aggregate()
    if agg.empty:
        print("[BMZ_DEEP] No predictions data.")
        return 1
    print(f"  {len(agg)} weekly snapshots, {agg['asof'].min().date()} -> {agg['asof'].max().date()}")

    print("[BMZ_DEEP] Loading SPY vol...")
    spy_vol = load_spy_vol()

    # ── ANALYSIS 1: ROBUSTNESS ACROSS SMOOTHING WINDOWS ─────────────────────
    print("\n" + "=" * 70)
    print(" ANALYSIS 1: ROBUSTNESS across smoothing windows")
    print("=" * 70)

    robustness_rows = []
    all_events = []
    for w in SLOPE_WINDOWS:
        agg_w = add_slope_signs(agg, window_weeks=w)
        events = agg_w[agg_w[f"sign_change_w{w}"]].copy()
        if events.empty:
            continue
        n_du = int(((events[f"sign_lag_w{w}"] < 0) & (events[f"sign_w{w}"] > 0)).sum())
        n_ud = int(((events[f"sign_lag_w{w}"] > 0) & (events[f"sign_w{w}"] < 0)).sum())

        # Compute lift for down→up events
        events["direction"] = events.apply(
            lambda r: "down->up" if (r[f"sign_lag_w{w}"] < 0 and r[f"sign_w{w}"] > 0)
                      else ("up->down" if (r[f"sign_lag_w{w}"] > 0 and r[f"sign_w{w}"] < 0)
                            else ""),
            axis=1)
        events["window"] = w
        for h in FWD_HORIZONS:
            events[f"fwd_h{h}_max"] = events["asof"].apply(
                lambda d: float(spy_vol.iloc[
                    spy_vol.index.searchsorted(d, side="left"):
                    spy_vol.index.searchsorted(d, side="left") + h
                ].max()) if spy_vol.index.searchsorted(d, side="left") + h < len(spy_vol) else np.nan)
        all_events.append(events[["asof", "direction", "window"] +
                                  [f"fwd_h{h}_max" for h in FWD_HORIZONS]])

        # Per-direction baseline comparison
        non_event_dates = agg_w[~agg_w[f"sign_change_w{w}"]
                                & agg_w[f"slope_w{w}"].notna()]["asof"].tolist()
        baseline_h21 = []
        for d in non_event_dates:
            i = spy_vol.index.searchsorted(d, side="left")
            if i + 21 < len(spy_vol):
                baseline_h21.append(float(spy_vol.iloc[i:i+21].max()))
        baseline_mean = float(np.mean(baseline_h21)) if baseline_h21 else np.nan

        du = events[events["direction"] == "down->up"]["fwd_h21_max"].dropna()
        ud = events[events["direction"] == "up->down"]["fwd_h21_max"].dropna()
        lift_du = float(du.mean() / baseline_mean) if (len(du) > 0 and baseline_mean) else np.nan
        lift_ud = float(ud.mean() / baseline_mean) if (len(ud) > 0 and baseline_mean) else np.nan

        robustness_rows.append({"window_weeks": w, "n_down_up": n_du, "n_up_down": n_ud,
                                "baseline_h21_max_mean": baseline_mean,
                                "down_up_h21_max_mean": float(du.mean()) if len(du) else np.nan,
                                "up_down_h21_max_mean": float(ud.mean()) if len(ud) else np.nan,
                                "lift_down_up": lift_du, "lift_up_down": lift_ud})

    rob_df = pd.DataFrame(robustness_rows)
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:.3f}"):
        print(rob_df.to_string(index=False))

    # ── ANALYSIS 2: LEAD TIME for down→up events at 12-week (canonical) ─────
    print("\n" + "=" * 70)
    print(" ANALYSIS 2: LEAD TIME for down→up events (12-week canonical)")
    print("=" * 70)

    agg12 = add_slope_signs(agg, window_weeks=12)
    du_events = agg12[
        agg12["sign_change_w12"]
        & (agg12["sign_lag_w12"] < 0) & (agg12["sign_w12"] > 0)
    ].copy()

    lead_rows = []
    for _, ev in du_events.iterrows():
        d = ev["asof"]
        thresh = shock_threshold_at(spy_vol, d)
        result = did_shock_happen(spy_vol, d, SHOCK_DEFINITION_HORIZON, thresh)
        lead_rows.append({
            "event_date": d.date().isoformat(),
            "shock_threshold_spy_vol": result.get("threshold", np.nan),
            "shock_within_42bd": result["shock"],
            "lead_bd_to_first_cross": result["lead_bd"],
            "fwd_42bd_peak_vol": result["peak"],
        })
    lead_df = pd.DataFrame(lead_rows)
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:.3f}"):
        print(lead_df.to_string(index=False))

    hits = lead_df[lead_df["shock_within_42bd"]]
    misses = lead_df[~lead_df["shock_within_42bd"]]
    print(f"\n  Hit rate (down→up events that preceded SPY vol > P90 within 42 BD):")
    print(f"    {len(hits)} / {len(lead_df)} = {len(hits)/max(len(lead_df),1):.1%}")
    if len(hits) > 0:
        lead_bds = hits["lead_bd_to_first_cross"].astype(float)
        print(f"  Lead time (BD to first shock-threshold cross):")
        print(f"    mean: {lead_bds.mean():.1f}   median: {lead_bds.median():.1f}   p25: {lead_bds.quantile(0.25):.1f}   p75: {lead_bds.quantile(0.75):.1f}")

    # ── ANALYSIS 3: LEVEL vs SLOPE — does absolute β_mz add info? ────────────
    print("\n" + "=" * 70)
    print(" ANALYSIS 3: LEVEL vs SLOPE — does absolute β_mz add info?")
    print("=" * 70)

    agg12["fwd_spy_vol_42d"] = agg12["asof"].apply(
        lambda d: float(spy_vol.iloc[
            spy_vol.index.searchsorted(d, side="left"):
            spy_vol.index.searchsorted(d, side="left") + 42
        ].max()) if spy_vol.index.searchsorted(d, side="left") + 42 < len(spy_vol) else np.nan)

    valid = agg12.dropna(subset=["mean_bmz", "slope_w12", "fwd_spy_vol_42d"])
    ic_level = float(valid["mean_bmz"].corr(valid["fwd_spy_vol_42d"], method="spearman"))
    ic_slope = float(valid["slope_w12"].corr(valid["fwd_spy_vol_42d"], method="spearman"))
    # Joint (rank-summed proxy)
    valid_s = valid.copy()
    valid_s["combined"] = valid_s["mean_bmz"].rank() + valid_s["slope_w12"].rank()
    ic_combined = float(valid_s["combined"].corr(valid_s["fwd_spy_vol_42d"], method="spearman"))
    print(f"  IC(mean_bmz LEVEL,   fwd_spy_vol_42d): {ic_level:+.3f}")
    print(f"  IC(slope_w12 SLOPE,  fwd_spy_vol_42d): {ic_slope:+.3f}")
    print(f"  IC(LEVEL + SLOPE combined,  fwd_spy_vol_42d): {ic_combined:+.3f}")
    print(f"  n = {len(valid)}")
    if abs(ic_combined) > max(abs(ic_level), abs(ic_slope)) + 0.02:
        print(f"  → Combined ADDS information beyond level OR slope alone")
    else:
        print(f"  → Combined doesn't materially beat the better single component")

    # ── ANALYSIS 4: CURRENT STATE ────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(" ANALYSIS 4: CURRENT STATE — what is the signal saying right now?")
    print("=" * 70)
    last = agg12.dropna(subset=["slope_w12"]).iloc[-1]
    pct_of_history = (agg12["mean_bmz"] < last["mean_bmz"]).mean()
    print(f"  Latest snapshot: {last['asof'].date()}")
    print(f"  Universe-mean β_mz: {last['mean_bmz']:.3f}  (P{pct_of_history*100:.0f} of historical)")
    print(f"  12-week slope: {last['slope_w12']:+.4f}  ({'HEATING (model under-predicting more)' if last['slope_w12'] > 0 else 'COOLING (model over-predicting more)'})")
    sign_now = "positive" if last["slope_w12"] > 0 else "negative"
    # Find most recent sign change
    recent_changes = agg12[agg12["sign_change_w12"] & (agg12["asof"] <= last["asof"])].tail(3)
    print(f"  Last 3 sign changes:")
    for _, r in recent_changes.iterrows():
        direction = "down->up" if r["sign_w12"] > 0 else "up->down"
        bd_ago = int(np.busday_count(r["asof"].date(), last["asof"].date()))
        print(f"    {r['asof'].date()}  {direction}  ({bd_ago} BD ago)")

    # ── SAVE OUTPUTS ──────────────────────────────────────────────────────────
    rob_df.to_csv(OUT_DIR / "beta_mz_robustness.csv", index=False)
    lead_df.to_csv(OUT_DIR / "beta_mz_event_table.csv", index=False)
    if all_events:
        pd.concat(all_events, ignore_index=True).to_csv(
            OUT_DIR / "beta_mz_all_events.csv", index=False)
    agg12.to_csv(OUT_DIR / "beta_mz_weekly_timeseries.csv", index=False)
    print(f"\n[BMZ_DEEP] Wrote outputs to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

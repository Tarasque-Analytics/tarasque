"""
bundle_risk_payloads.py — Build per-ticker {TICKER}_Risk.json contracts for the
web app's stock-detail page.

Reads (post-corpus + post-overlay state):
  predictions_{TICKER}.csv             — long-form OOS predictions, all horizons
  forecasts/forecast_{date}.csv        — current cycle forecast point
  mz_calibration.csv                   — EW MZ betas per (ticker, horizon)
  regime_2x2.csv                       — β_mkt + β_mz + quadrant
  tail_log/{TICKER}_events.csv         — lifetime tail events
  q15_coverage_offsets.csv             — per-ticker q15 floor offset

Writes one JSON per ticker following spec §6A in LAUNCH_PLAN_2026-05-01.md:
  payloads/risk/{TICKER}_Risk.json
    - one ticker per file (matches supabase storage convention)
    - all 3 horizons inside each file
    - forecast + current_state + structural + lifetime_stats + history blocks

Run:
    python -m model.pipeline.scripts.bundle_risk_payloads
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ..utils import DECIMAL_PRECISION, round_json_dict


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "model" / "pipeline" / "results"
OUT_DIR = RESULTS_DIR / "payloads" / "risk"
TAIL_DIR = RESULTS_DIR / "tail_log"
TAIL_HIGH = 0.85
EXTREME = 0.95
WARMUP_DAYS = 252


def safe_read_csv(path: Path, **kw) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    try:
        return pd.read_csv(path, **kw)
    except Exception as e:
        print(f"[BUNDLE] {path.name}: read failed ({e})")
        return None


def lookup_forecast(forecasts: pd.DataFrame, ticker: str) -> dict:
    if forecasts is None:
        return {}
    sub = forecasts[forecasts["ticker"] == ticker]
    if sub.empty:
        return {}
    row = sub.iloc[-1]
    return {
        "h21": float(row.get("forecast_h21", np.nan)),
        "h63": float(row.get("forecast_h63", np.nan)),
        "h126": float(row.get("forecast_h126", np.nan)),
        "cycle_start_date": str(row.get("cycle_start_date", "")),
        "cycle_window_end": str(row.get("window_end_date", "")),
    }


def lookup_regime(regime: pd.DataFrame, ticker: str) -> dict:
    if regime is None:
        return {}
    sub = regime[regime["ticker"] == ticker]
    if sub.empty:
        return {}
    row = sub.iloc[0]
    return {
        "beta_mkt_252d": float(row.get("beta_mkt", np.nan)),
        "beta_mz_h21": float(row.get("beta_mz_h21", np.nan)),
        "beta_mz_h63": float(row.get("beta_mz_h63", np.nan)),
        "beta_mz_h126": float(row.get("beta_mz_h126", np.nan)),
        "quadrant": str(row.get("quadrant_h21", "n/a")),
    }


def current_state(preds_h21: pd.DataFrame) -> dict:
    """Tail percentile + days-in-state from H=21 prediction history."""
    if preds_h21.empty:
        return {}
    sub = preds_h21.sort_values("date").reset_index(drop=True)
    sub["percentile"] = sub["y_true"].expanding(min_periods=WARMUP_DAYS).rank(pct=True)
    last = sub.iloc[-1]
    p = last["percentile"]
    if pd.isna(p):
        regime = "warmup"
    elif p >= EXTREME:
        regime = "extreme"
    elif p >= TAIL_HIGH:
        regime = "tail"
    else:
        regime = "normal"

    # Days since last regime change
    state = (sub["percentile"] >= TAIL_HIGH).astype(int).fillna(-1)
    if len(state) > 1:
        state_changes = state != state.shift(1)
        last_change = state_changes[::-1].idxmax() if state_changes.any() else 0
        days_in_state = (last["date"] - sub["date"].iloc[last_change]).days
    else:
        days_in_state = 0

    return {
        "percentile_h21": float(p) if pd.notna(p) else None,
        "regime": regime,
        "days_in_state": int(days_in_state),
        "as_of": str(last["date"].date() if hasattr(last["date"], "date")
                     else last["date"])[:10],
    }


def lifetime_stats(events: pd.DataFrame) -> dict:
    if events is None or events.empty:
        return {"tail_entries": 0, "extreme_entries": 0,
                "median_tail_duration_days": None, "pct_time_in_tail": None}
    n_tail = (events["event_type"] == "tail_entry").sum()
    n_ext = (events["event_type"] == "extreme_entry").sum()
    durations = events.loc[events["event_type"] == "tail_exit",
                           "duration_days"].dropna()
    median_dur = float(durations.median()) if len(durations) > 0 else None
    return {
        "tail_entries": int(n_tail),
        "extreme_entries": int(n_ext),
        "median_tail_duration_days": median_dur,
    }


def build_history(preds: pd.DataFrame, max_points: int = 1500) -> dict:
    """Sparse arrays for the chart layer; downsampled to keep payload size sane."""
    if preds.empty:
        return {}
    h21 = preds[preds["horizon"] == 21].sort_values("date").reset_index(drop=True)
    if h21.empty:
        return {}
    if len(h21) > max_points:
        # Take every Nth row to land near max_points
        step = max(1, len(h21) // max_points)
        h21 = h21.iloc[::step].copy()
    h21["percentile"] = h21["y_true"].expanding(min_periods=WARMUP_DAYS).rank(pct=True)

    out = {
        "dates": h21["date"].dt.strftime("%Y-%m-%d").tolist(),
        "y_true": h21["y_true"].round(6).tolist(),
        "y_pred_h21": h21["y_pred"].round(6).tolist(),
    }
    if "y_pred_q15" in h21.columns:
        out["y_pred_q15"] = h21["y_pred_q15"].round(6).tolist()
    out["percentile"] = [None if pd.isna(v) else round(float(v), 4)
                         for v in h21["percentile"]]
    return out


def process_ticker(
    ticker: str, preds: pd.DataFrame,
    forecasts: pd.DataFrame, regime: pd.DataFrame,
) -> Optional[dict]:
    if preds.empty:
        return None
    h21 = preds[preds["horizon"] == 21].sort_values("date").reset_index(drop=True)

    events_path = TAIL_DIR / f"{ticker}_events.csv"
    events = safe_read_csv(events_path)
    if events is not None and "date" in events.columns:
        events["date"] = pd.to_datetime(events["date"], errors="coerce")

    # Compute pct_time_in_tail directly from prediction history
    sub = h21.copy()
    sub["percentile"] = sub["y_true"].expanding(min_periods=WARMUP_DAYS).rank(pct=True)
    valid = sub["percentile"].dropna()
    pct_time = float((valid >= TAIL_HIGH).mean()) if len(valid) > 0 else None

    payload = {
        "ticker": ticker,
        "as_of": str(h21["date"].max().date() if hasattr(h21["date"].max(), "date")
                     else h21["date"].max())[:10],
        "forecast": lookup_forecast(forecasts, ticker),
        "current_state": current_state(h21),
        "structural": lookup_regime(regime, ticker),
        "lifetime_stats": {**lifetime_stats(events), "pct_time_in_tail": pct_time},
        "history": build_history(preds),
    }
    return payload


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load aggregates once
    forecasts_path = RESULTS_DIR / "forecasts"
    forecasts = None
    if forecasts_path.exists():
        # Latest forecast_*.csv
        candidates = sorted(forecasts_path.glob("forecast_*.csv"))
        if candidates:
            forecasts = safe_read_csv(candidates[-1])
            print(f"[BUNDLE] Loaded forecast {candidates[-1].name} ({len(forecasts)} rows)")

    regime = safe_read_csv(RESULTS_DIR / "regime_2x2.csv")
    if regime is not None:
        print(f"[BUNDLE] Loaded regime_2x2.csv ({len(regime)} rows)")

    # Iterate per-ticker prediction files
    pred_files = sorted(RESULTS_DIR.glob("predictions_*.csv"))
    if not pred_files:
        print("[BUNDLE] No per-ticker predictions found.")
        return

    written = 0
    for f in pred_files:
        ticker = f.stem.replace("predictions_", "")
        try:
            preds = pd.read_csv(f, parse_dates=["date"])
        except Exception as e:
            print(f"[BUNDLE] {f.name}: skipped ({e})")
            continue
        payload = process_ticker(ticker, preds, forecasts, regime)
        if payload is None:
            continue
        payload = round_json_dict(payload)
        out = OUT_DIR / f"{ticker}_Risk.json"
        with open(out, "w") as fp:
            json.dump(payload, fp, indent=2, default=str)
        written += 1
    print(f"[BUNDLE] Wrote {written} per-ticker Risk JSONs to {OUT_DIR}")


if __name__ == "__main__":
    main()

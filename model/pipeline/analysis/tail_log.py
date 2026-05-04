"""
tail_log.py — Per-ticker visual tail event log + sector aggregation.

Records when realized vol crosses into / out of the upper tail (per-ticker
historical distribution) and produces a time-series visualization of:
  - realized RV with expanding-window quantile bands (P25/P50/P85/P95)
  - model forecast (y_pred) and floor (y_pred_q15) overlay
  - prediction residuals with tail-entry markers
  - current state summary (percentile, days-in-tail, MZ beta, quadrant)

Tail events are computed using EXPANDING-window percentiles per ticker so there's
no lookahead. A "tail entry" fires when y_true crosses above the rolling P85
threshold for the first time after being below it; a "tail exit" fires on the
return crossing.

Outputs (per ticker):
  model/pipeline/results/tail_log/{TICKER}_tail.png
  model/pipeline/results/tail_log/{TICKER}_events.csv

Aggregate:
  model/pipeline/results/tail_log/tail_events_all.csv
  model/pipeline/results/tail_log/sector_tail_summary.csv  (when corpus available)

Run:
    python -m model.pipeline.analysis.tail_log --ticker AAPL
    python -m model.pipeline.analysis.tail_log --all                # corpus
    python -m model.pipeline.analysis.tail_log --sectors            # add sector roll-up
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from ..config import load_config
from ..data_loader import ParquetStore
from ..utils import DECIMAL_PRECISION, round_for_output


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "model" / "pipeline" / "results"
OUT_DIR = RESULTS_DIR / "tail_log"

# Tail thresholds (percentile of own history, expanding window).
TAIL_HIGH = 0.85   # top tail entry threshold
EXTREME = 0.95     # extreme event threshold
HORIZON_PRIMARY = 21  # tail logging is most actionable at H=21
WARMUP_DAYS = 252  # need 1y of data before computing percentiles


def expanding_percentile(series: pd.Series) -> pd.Series:
    """Expanding-window empirical CDF rank (no lookahead)."""
    return series.expanding(min_periods=WARMUP_DAYS).rank(pct=True)


def expanding_quantiles(series: pd.Series, qs=(0.25, 0.50, 0.85, 0.95)) -> pd.DataFrame:
    """Expanding-window quantile values (no lookahead)."""
    out = {}
    for q in qs:
        out[f"q{int(q*100)}"] = series.expanding(min_periods=WARMUP_DAYS).quantile(q)
    return pd.DataFrame(out, index=series.index)


def detect_tail_events(df: pd.DataFrame) -> pd.DataFrame:
    """
    df has columns: date, y_true, percentile, q85, q95.
    Returns event log: date, event_type, realized_rv, predicted_rv, percentile.
    """
    events = []
    in_tail = False
    in_extreme = False
    last_state_change = None
    for _, row in df.iterrows():
        if pd.isna(row["percentile"]):
            continue
        p = row["percentile"]
        # Extreme events
        if not in_extreme and p >= EXTREME:
            events.append({
                "date": row["date"],
                "event_type": "extreme_entry",
                "realized_rv": row["y_true"],
                "predicted_rv": row.get("y_pred", np.nan),
                "percentile": p,
            })
            in_extreme = True
        elif in_extreme and p < EXTREME:
            events.append({
                "date": row["date"],
                "event_type": "extreme_exit",
                "realized_rv": row["y_true"],
                "predicted_rv": row.get("y_pred", np.nan),
                "percentile": p,
            })
            in_extreme = False
        # Tail entries (above P85) — track separately from extreme
        if not in_tail and p >= TAIL_HIGH:
            events.append({
                "date": row["date"],
                "event_type": "tail_entry",
                "realized_rv": row["y_true"],
                "predicted_rv": row.get("y_pred", np.nan),
                "percentile": p,
            })
            in_tail = True
            last_state_change = row["date"]
        elif in_tail and p < TAIL_HIGH:
            duration = (row["date"] - last_state_change).days if last_state_change is not None else None
            events.append({
                "date": row["date"],
                "event_type": "tail_exit",
                "realized_rv": row["y_true"],
                "predicted_rv": row.get("y_pred", np.nan),
                "percentile": p,
                "duration_days": duration,
            })
            in_tail = False
            last_state_change = row["date"]
    return pd.DataFrame(events)


def load_predictions(ticker: str) -> Optional[pd.DataFrame]:
    """Load predictions_{TICKER}.csv (long-form)."""
    p = RESULTS_DIR / f"predictions_{ticker}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["date"])
    return df


def load_regime_label(ticker: str) -> dict:
    """Pull the (β_mkt, β_mz, quadrant) row from regime_2x2.csv if available."""
    p = RESULTS_DIR / "regime_2x2.csv"
    if not p.exists():
        return {}
    rg = pd.read_csv(p)
    row = rg[rg["ticker"] == ticker]
    if row.empty:
        return {}
    return row.iloc[0].to_dict()


def build_tail_frame(preds: pd.DataFrame, horizon: int = HORIZON_PRIMARY) -> pd.DataFrame:
    """Filter to one horizon and compute percentiles + quantile bands."""
    sub = preds[preds["horizon"] == horizon].sort_values("date").reset_index(drop=True)
    if sub.empty:
        return sub
    sub["percentile"] = expanding_percentile(sub["y_true"])
    bands = expanding_quantiles(sub["y_true"])
    sub = pd.concat([sub, bands], axis=1)
    return sub


def plot_ticker(ticker: str, frame: pd.DataFrame, events: pd.DataFrame,
                regime: dict, out_path: Path) -> None:
    """3-panel + summary card figure."""
    if frame.empty:
        print(f"[TAIL_LOG] {ticker}: no predictions, skipping plot.")
        return

    fig = plt.figure(figsize=(14, 9))
    gs = fig.add_gridspec(3, 4, height_ratios=[2.2, 2.2, 1], hspace=0.35, wspace=0.35)

    # Panel 1: Realized vol + quantile bands
    ax1 = fig.add_subplot(gs[0, :3])
    ax1.fill_between(frame["date"], frame["q25"], frame["q85"],
                     alpha=0.15, color="steelblue", label="P25-P85 (typical)")
    ax1.fill_between(frame["date"], frame["q85"], frame["q95"],
                     alpha=0.20, color="orange", label="P85-P95 (tail)")
    ax1.fill_between(frame["date"], frame["q95"],
                     frame["y_true"].where(frame["y_true"] > frame["q95"], frame["q95"]),
                     alpha=0.30, color="crimson", label="P95+ (extreme)")
    ax1.plot(frame["date"], frame["y_true"], color="black", linewidth=0.8, label="Realized RV")
    ax1.plot(frame["date"], frame["q50"], color="steelblue", linewidth=0.7,
             linestyle="--", alpha=0.6, label="Median")
    ax1.set_ylabel("Annualized RV")
    ax1.set_title(f"{ticker} — H=21 realized vol with expanding-window quantile bands")
    ax1.legend(loc="upper left", fontsize=8)
    ax1.grid(True, alpha=0.25)

    # Panel 2: Realized vs predicted + floor
    ax2 = fig.add_subplot(gs[1, :3], sharex=ax1)
    ax2.plot(frame["date"], frame["y_true"], color="black", linewidth=0.8, label="Realized")
    ax2.plot(frame["date"], frame["y_pred"], color="#1f77b4", linewidth=0.8, alpha=0.85,
             label="Forecast (point)")
    if "y_pred_q15" in frame.columns:
        ax2.plot(frame["date"], frame["y_pred_q15"], color="#2ca02c", linewidth=0.8,
                 alpha=0.7, label="P15 floor")
    ax2.set_ylabel("Annualized RV")
    ax2.set_title("Realized vs forecast")
    ax2.legend(loc="upper left", fontsize=8)
    ax2.grid(True, alpha=0.25)

    # Panel 3: Tail-state strip + event markers
    ax3 = fig.add_subplot(gs[2, :3], sharex=ax1)
    in_tail = frame["percentile"] >= TAIL_HIGH
    in_extreme = frame["percentile"] >= EXTREME
    # Color strip: green=normal, orange=tail, red=extreme
    state_color = np.where(in_extreme, 2, np.where(in_tail, 1, 0))
    ax3.fill_between(frame["date"], 0, 1, where=(state_color == 1), color="orange",
                     alpha=0.5, label="In tail (P85+)")
    ax3.fill_between(frame["date"], 0, 1, where=(state_color == 2), color="crimson",
                     alpha=0.6, label="Extreme (P95+)")
    if not events.empty:
        for _, ev in events.iterrows():
            color = {"extreme_entry": "darkred", "extreme_exit": "lightcoral",
                     "tail_entry": "darkorange", "tail_exit": "wheat"}.get(
                         ev["event_type"], "gray")
            ax3.axvline(ev["date"], color=color, alpha=0.7, linewidth=0.6)
    ax3.set_ylim(0, 1)
    ax3.set_yticks([])
    ax3.set_title("Tail regime strip (orange=P85+, red=P95+)")
    ax3.set_xlabel("Date")
    ax3.grid(True, alpha=0.15, axis="x")

    # Summary card on the right
    ax_card = fig.add_subplot(gs[:, 3])
    ax_card.axis("off")
    last = frame.iloc[-1]
    last_p = last["percentile"]
    last_state = "EXTREME" if last_p >= EXTREME else ("IN TAIL" if last_p >= TAIL_HIGH else "NORMAL")

    days_in_state = 0
    if not events.empty:
        last_state_change = events.iloc[-1]
        days_in_state = (last["date"] - last_state_change["date"]).days

    n_extreme = (events["event_type"] == "extreme_entry").sum() if not events.empty else 0
    n_tail = (events["event_type"] == "tail_entry").sum() if not events.empty else 0

    bmkt = regime.get("beta_mkt", np.nan)
    bmz = regime.get("beta_mz_h21", np.nan)
    quad = regime.get("quadrant_h21", "n/a")

    card_lines = [
        f"$\\bf{{{ticker}}}$ — H=21 tail summary",
        "",
        f"As of: {last['date'].date()}",
        f"Realized RV: {last['y_true']:.3f}",
        f"Forecast: {last['y_pred']:.3f}",
        f"P15 floor: {last.get('y_pred_q15', np.nan):.3f}",
        "",
        f"Percentile: {last_p:.2%}" if pd.notna(last_p) else "Percentile: warmup",
        f"State: $\\bf{{{last_state}}}$",
        f"Days in state: {days_in_state}",
        "",
        f"Lifetime tail entries: {n_tail}",
        f"Lifetime extreme entries: {n_extreme}",
        "",
        f"$\\beta_{{mkt}}$: {bmkt:.2f}" if pd.notna(bmkt) else "β_mkt: n/a",
        f"$\\beta_{{mz}}$: {bmz:.2f}" if pd.notna(bmz) else "β_mz: n/a",
        f"Regime: {quad}",
    ]
    ax_card.text(0.05, 0.95, "\n".join(card_lines), transform=ax_card.transAxes,
                 verticalalignment="top", fontsize=10, family="monospace",
                 bbox=dict(boxstyle="round,pad=0.6", facecolor="#f5f5f5",
                           edgecolor="gray"))

    # X-axis formatting
    for ax in (ax1, ax2, ax3):
        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    plt.suptitle(f"{ticker} — Tail Event Log", fontsize=13, y=0.995)
    plt.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"[TAIL_LOG] {ticker}: wrote {out_path.name}")


def process_ticker(ticker: str) -> Optional[pd.DataFrame]:
    """Full per-ticker pipeline. Returns event log dataframe."""
    preds = load_predictions(ticker)
    if preds is None:
        print(f"[TAIL_LOG] {ticker}: no predictions_{ticker}.csv found, skipping.")
        return None

    frame = build_tail_frame(preds, horizon=HORIZON_PRIMARY)
    if frame.empty:
        return None

    events = detect_tail_events(frame)
    events.insert(0, "ticker", ticker)
    events = round_for_output(events, DECIMAL_PRECISION)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    events_path = OUT_DIR / f"{ticker}_events.csv"
    events.to_csv(events_path, index=False)

    regime = load_regime_label(ticker)
    plot_ticker(ticker, frame, events, regime, OUT_DIR / f"{ticker}_tail.png")
    return events


def aggregate_corpus(all_tickers: list[str]) -> None:
    """Concatenate per-ticker event logs into corpus aggregate."""
    frames = []
    for t in all_tickers:
        p = OUT_DIR / f"{t}_events.csv"
        if p.exists():
            frames.append(pd.read_csv(p, parse_dates=["date"]))
    if not frames:
        return
    agg = pd.concat(frames, ignore_index=True)
    agg = round_for_output(agg, DECIMAL_PRECISION)
    out = OUT_DIR / "tail_events_all.csv"
    agg.to_csv(out, index=False)
    print(f"[TAIL_LOG] Wrote corpus aggregate {out} ({len(agg)} events, "
          f"{agg['ticker'].nunique()} tickers)")


def aggregate_by_sector() -> None:
    """Per-sector tail-event counts and current state. Requires compustat_meta."""
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    try:
        meta = store.load("compustat_meta")
    except Exception:
        print("[TAIL_LOG] compustat_meta not available; skipping sector roll-up.")
        return
    if meta.empty or "gsector" not in meta.columns:
        print("[TAIL_LOG] compustat_meta missing gsector; skipping sector roll-up.")
        return

    agg_path = OUT_DIR / "tail_events_all.csv"
    if not agg_path.exists():
        print("[TAIL_LOG] tail_events_all.csv missing; run --all first.")
        return
    events = pd.read_csv(agg_path, parse_dates=["date"])
    sector_map = meta[["ticker", "gsector"]].drop_duplicates()
    events = events.merge(sector_map, on="ticker", how="left")

    # Per-sector summary: count of tail/extreme entries, top names by count
    summary = (events[events["event_type"].isin(["tail_entry", "extreme_entry"])]
               .groupby(["gsector", "event_type"])
               .size().unstack(fill_value=0).reset_index())
    summary = round_for_output(summary, DECIMAL_PRECISION)
    out = OUT_DIR / "sector_tail_summary.csv"
    summary.to_csv(out, index=False)
    print(f"[TAIL_LOG] Wrote sector summary {out}")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ticker", help="Single ticker")
    g.add_argument("--all", action="store_true", help="All tickers in config")
    ap.add_argument("--sectors", action="store_true",
                    help="After processing, aggregate by GICS sector")
    args = ap.parse_args()

    if args.ticker:
        process_ticker(args.ticker)
    else:
        dc, _, _ = load_config()
        for t in dc.tickers:
            process_ticker(t)
        aggregate_corpus(dc.tickers)
        if args.sectors:
            aggregate_by_sector()


if __name__ == "__main__":
    main()

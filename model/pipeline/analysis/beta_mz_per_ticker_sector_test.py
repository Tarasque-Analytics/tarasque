"""
beta_mz_per_ticker_sector_test.py -- Apply the universe-aggregate beta_mz sign-change
                                     test to PER-STOCK and PER-SECTOR beta_mz.

We've only tested the universe-mean beta_mz (1 series across 93 stocks). But every
ticker has its own beta_mz, and sector-aggregates are a natural intermediate that
maps to tradeable sector ETFs (XLF/XLK/XLE/XLV/XLI). Question: does an individual
stock's own beta_mz sign-change predict that stock's forward return? Does a sector
beta_mz predict its sector ETF?

PART A  PER-STOCK -- own beta_mz 12-wk slope sign-change events; forward 40-BD
        return on the same stock. Pool across all 93 names + breadth report.
PART B  PER-SECTOR -- aggregate beta_mz across each sector's tickers; sign-change
        events; forward 40-BD return on the matching SPDR sector ETF. Plus: does
        sector beta_mz beat the universe-aggregate beta_mz on its own sector?
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from ..config import load_config
from ..data_loader import ParquetStore
from .beta_mz_deep_dive import add_slope_signs, RESULTS_DIR
from .beta_mz_drawdown_value import cumulative_index, forward_window_metrics
from .beta_mz_multi_index_test import load_index_returns
from .beta_mz_panel import load_per_ticker_weekly, aggregate_subset

OUT_DIR = RESULTS_DIR / "validation"
HOLD = 40

SECTORS = {
    "Financials":  ("XLF", ["JPM","BAC","WFC","C","GS","MS","BLK","SCHW","AXP","USB"]),
    "Energy":      ("XLE", ["XOM","CVX","COP","EOG","MPC","PSX","SLB"]),
    "Technology":  ("XLK", ["AAPL","MSFT","NVDA","AMD","INTC","AVGO","CRM","ORCL",
                            "ADBE","CSCO","IBM","QCOM","TXN","AMAT","MU"]),
    "Healthcare":  ("XLV", ["UNH","JNJ","PFE","ABT","ABBV","TMO","MRK","BMY","AMGN",
                            "GILD","CVS","LLY"]),
    "Industrials": ("XLI", ["BA","HON","CAT","DE","GE","UPS","FDX","LMT","NOC","RTX","MMM"]),
}


def stock_prices() -> dict:
    dc, _, _ = load_config()
    oh = ParquetStore(dc.base_dir).load("ohlcv")
    oh["date"] = pd.to_datetime(oh["date"], format="mixed")
    out = {}
    for tk, g in oh.drop_duplicates(["date", "ticker"]).groupby("ticker"):
        out[tk] = g.sort_values("date").set_index("date")["prc"].ffill()
    return out


def fwd_log_return(price: pd.Series, d: pd.Timestamp, h: int) -> float:
    i = price.index.searchsorted(d, side="left")
    if i + h >= len(price):
        return np.nan
    p0, p1 = price.iloc[i], price.iloc[i + h]
    return float(np.log(p1 / p0)) if p0 > 0 and p1 > 0 else np.nan


def event_dates(signed: pd.DataFrame):
    cool = signed[signed["sign_change_w12"] & (signed["sign_lag_w12"] > 0)
                  & (signed["sign_w12"] < 0)]["asof"].tolist()
    heat = signed[signed["sign_change_w12"] & (signed["sign_lag_w12"] < 0)
                  & (signed["sign_w12"] > 0)]["asof"].tolist()
    return cool, heat


def stats_block(name: str, rets: list) -> dict:
    a = np.array([r for r in rets if np.isfinite(r)], dtype=float)
    if len(a) < 5:
        return {"label": name, "n": len(a), "mean": np.nan, "hit": np.nan, "t": np.nan}
    t = a.mean() / (a.std(ddof=1) / np.sqrt(len(a))) if a.std() > 0 else np.nan
    return {"label": name, "n": len(a), "mean": float(a.mean()),
            "median": float(np.median(a)), "hit": float((a > 0).mean()), "t": float(t)}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    panel = load_per_ticker_weekly()
    prices = stock_prices()
    all_tickers = sorted(panel["ticker"].unique())
    print(f"[BMZ_PT_SEC] panel: {len(panel):,} rows | {len(all_tickers)} tickers")

    # ── PART A: PER-STOCK own-beta_mz sign-change events on own forward return ──
    print("\n" + "=" * 82)
    print(f" PART A: PER-STOCK own beta_mz sign-change -> own {HOLD}-BD fwd return")
    print("=" * 82)
    all_cool, all_heat = [], []     # cool = LONG bet (+ret); heat = SHORT bet (-ret)
    per_ticker = []
    for tk in all_tickers:
        own = panel[panel["ticker"] == tk][["asof", "beta_mz"]].rename(
            columns={"beta_mz": "mean_bmz"}).sort_values("asof").reset_index(drop=True)
        if len(own) < 60:
            continue
        signed = add_slope_signs(own, 12)
        cool, heat = event_dates(signed)
        if tk not in prices:
            continue
        px = prices[tk]
        cool_r = [fwd_log_return(px, d, HOLD) for d in cool]
        heat_r = [fwd_log_return(px, d, HOLD) for d in heat]
        cool_r = [r for r in cool_r if np.isfinite(r)]
        heat_r = [r for r in heat_r if np.isfinite(r)]
        all_cool.extend(cool_r)
        all_heat.extend([-r for r in heat_r])   # short bet
        per_ticker.append({"ticker": tk, "n_cool": len(cool_r), "n_heat": len(heat_r),
                           "cool_mean": float(np.mean(cool_r)) if cool_r else np.nan,
                           "heat_short_mean": float(-np.mean(heat_r)) if heat_r else np.nan})
    print(f"  pooled across {len(per_ticker)} tickers:")
    for r in [stats_block("cool->LONG  (per-stock)", all_cool),
              stats_block("heat->SHORT (per-stock)", all_heat)]:
        print(f"    {r['label']:30s}: n={r['n']:4d}  mean {r['mean']:+.3%}  "
              f"median {r['median']:+.3%}  hit {r['hit']:.0%}  naive t {r['t']:+.2f}")
    pt = pd.DataFrame(per_ticker)
    pos_cool = float((pt["cool_mean"] > 0).mean())
    pos_heat = float((pt["heat_short_mean"] > 0).mean())
    print(f"  breadth: {pos_cool:.0%} of {len(pt)} tickers had positive cool->LONG mean | "
          f"{pos_heat:.0%} positive heat->SHORT mean")
    print("  (naive t ignores cross-stock correlation on overlapping dates -> treat as upper bound)")
    pt.to_csv(OUT_DIR / "beta_mz_per_ticker_events.csv", index=False)

    # ── PART B: PER-SECTOR sector-beta_mz -> sector ETF fwd return ─────────────
    print("\n" + "=" * 82)
    print(f" PART B: PER-SECTOR aggregate beta_mz sign-change -> sector ETF {HOLD}-BD fwd return")
    print("=" * 82)
    # universe baseline for comparison
    uni = add_slope_signs(aggregate_subset(panel), 12)
    uni_cool, uni_heat = event_dates(uni)
    sec_rows = []
    for sec, (etf, members) in SECTORS.items():
        mem = [t for t in members if t in all_tickers]
        if len(mem) < 5:
            print(f"  {sec}: too few members ({len(mem)}); skipping")
            continue
        sa = add_slope_signs(aggregate_subset(panel, mem), 12)
        sc, sh = event_dates(sa)
        etf_price = cumulative_index(load_index_returns(etf))
        c_sec = [fwd_log_return(etf_price, d, HOLD) for d in sc]
        h_sec = [fwd_log_return(etf_price, d, HOLD) for d in sh]
        c_uni = [fwd_log_return(etf_price, d, HOLD) for d in uni_cool]
        h_uni = [fwd_log_return(etf_price, d, HOLD) for d in uni_heat]
        cs = stats_block("sec_cool", c_sec); hs = stats_block("sec_heat", [-r for r in h_sec])
        cu = stats_block("uni_cool", c_uni); hu = stats_block("uni_heat", [-r for r in h_uni])
        print(f"\n  {sec} (n_members={len(mem)}, ETF={etf}):")
        print(f"    SECTOR-bmz cool->LONG : n={cs['n']:2d}  mean {cs['mean']:+.3%}  "
              f"hit {cs['hit']:.0%}  t {cs['t']:+.2f}")
        print(f"    SECTOR-bmz heat->SHORT: n={hs['n']:2d}  mean {hs['mean']:+.3%}  "
              f"hit {hs['hit']:.0%}  t {hs['t']:+.2f}")
        print(f"    UNIVERSE-bmz cool on {etf:>3s}: n={cu['n']:2d}  mean {cu['mean']:+.3%}  hit {cu['hit']:.0%}")
        print(f"    UNIVERSE-bmz heat on {etf:>3s}: n={hu['n']:2d}  mean {hu['mean']:+.3%}  hit {hu['hit']:.0%}")
        sec_rows.append({"sector": sec, "etf": etf, "n_members": len(mem),
                         "sec_cool_n": cs["n"], "sec_cool_mean": cs["mean"], "sec_cool_hit": cs["hit"], "sec_cool_t": cs["t"],
                         "sec_heat_n": hs["n"], "sec_heat_mean": hs["mean"], "sec_heat_hit": hs["hit"], "sec_heat_t": hs["t"],
                         "uni_cool_mean": cu["mean"], "uni_cool_hit": cu["hit"],
                         "uni_heat_mean": hu["mean"], "uni_heat_hit": hu["hit"]})
    sec_df = pd.DataFrame(sec_rows)
    sec_df.to_csv(OUT_DIR / "beta_mz_per_sector_events.csv", index=False)

    # ── PART C: does sector-bmz BEAT universe-bmz on its own sector? ──────────
    print("\n" + "=" * 82)
    print(" PART C: does sector-specific beta_mz beat universe-aggregate on its sector?")
    print("=" * 82)
    print(f"  {'sector':<12} {'COOL sec vs uni mean':>22} {'HEAT(short) sec vs uni mean':>30}")
    for r in sec_rows:
        ds = (r["sec_cool_mean"] - r["uni_cool_mean"]) * 100
        dh = (r["sec_heat_mean"] - r["uni_heat_mean"]) * 100
        verdict_c = "sec wins" if ds > 0.5 else "uni wins" if ds < -0.5 else "tie"
        verdict_h = "sec wins" if dh > 0.5 else "uni wins" if dh < -0.5 else "tie"
        print(f"  {r['sector']:<12} {ds:>+8.2f}pp ({verdict_c:>8})    {dh:>+8.2f}pp ({verdict_h:>8})")

    print("\n[BMZ_PT_SEC] Wrote 2 CSVs to", OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())

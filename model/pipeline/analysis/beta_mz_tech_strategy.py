"""
beta_mz_tech_strategy.py -- Tech-sector beta_mz overlay on XLK, mirroring the
                            SPY/universe-beta_mz treatment that produced the
                            headline Sharpe 1.50 / $464k results.

Why Tech: in the per-sector test (beta_mz_per_ticker_sector_test) Tech was the
only sector where both legs worked -- cool->LONG +5.7% (t=3.7) AND heat->SHORT
-2.8% (t=-1.8) on XLK. The other four sectors had a dead short leg.

PART 1  Variant overlays on XLK using TECH-bmz state (long when slope<=0):
        BH, CASH, HALF, LONG_SHORT_{70_30,50_50,30_70}, FULL_FLIP, 25%TILT_LEV.
        Compare to BH XLK and to UNIVERSE-bmz CASH on XLK (which previously LOST
        on Sharpe -- the only sector where universe-bmz failed).
PART 2  Event-driven holding-period sweep on XLK for the cool and heat legs.
        Headline-style answer for the directional bet horizon.
PART 3  Spanning regressions (HAC) -- does the TECH-bmz CASH overlay on XLK add
        over (a) HY-sizing on XLK, and (b) UNIVERSE-bmz sizing on XLK?
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from .beta_mz_deep_dive import add_slope_signs, RESULTS_DIR
from .beta_mz_defensive_overlay import load_macro
from .beta_mz_drawdown_value import cumulative_index, max_drawdown, forward_window_metrics
from .beta_mz_multi_index_test import load_index_returns
from .beta_mz_panel import load_per_ticker_weekly, aggregate_subset
from .beta_mz_short_overlay import simulate, stats as overlay_stats, STRATEGIES, \
    FLIP_COST_BPS, BORROW_COST_BPS_ANNUAL
from .beta_mz_cooling_incremental import (
    hy_weekly_frame, calm_mask_daily, overlay_returns, sharpe_stats, START_DATE,
)

OUT_DIR = RESULTS_DIR / "validation"
STARTING = 100_000
HAC_LAGS = 40
TECH = ["AAPL","MSFT","NVDA","AMD","INTC","AVGO","CRM","ORCL",
        "ADBE","CSCO","IBM","QCOM","TXN","AMAT","MU"]
EXTENDED_STRATEGIES = dict(STRATEGIES)
EXTENDED_STRATEGIES["TILT_25_LEV"] = (1.25, 0.0, 0.75, 0.25)   # the SPY headline form


def event_dates(signed: pd.DataFrame):
    cool = signed[signed["sign_change_w12"] & (signed["sign_lag_w12"] > 0) &
                  (signed["sign_w12"] < 0)]["asof"].tolist()
    heat = signed[signed["sign_change_w12"] & (signed["sign_lag_w12"] < 0) &
                  (signed["sign_w12"] > 0)]["asof"].tolist()
    return cool, heat


def hac_span(y: pd.Series, x: pd.Series) -> dict:
    d = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    res = sm.OLS(d["y"].to_numpy(float),
                 sm.add_constant(d["x"].to_numpy(float))).fit(
        cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    a = float(res.params[0] * 252)
    rv = float(np.std(res.resid, ddof=2) * np.sqrt(252))
    return {"ann_alpha": a, "t": float(res.tvalues[0]), "p": float(res.pvalues[0]),
            "beta": float(res.params[1]), "ir": a / rv if rv > 0 else np.nan,
            "corr": float(d["y"].corr(d["x"])), "n": int(len(d))}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    panel = load_per_ticker_weekly()
    tech_in = [t for t in TECH if t in panel["ticker"].unique()]
    print(f"[BMZ_TECH] {len(tech_in)} of {len(TECH)} Tech tickers in panel")
    tech_bmz = add_slope_signs(aggregate_subset(panel, tech_in), 12)
    uni_bmz = add_slope_signs(aggregate_subset(panel), 12)

    xlk_ret = load_index_returns("XLK")
    xlk_ret = xlk_ret[xlk_ret.index >= START_DATE]
    dates = xlk_ret.index
    print(f"  XLK: {len(dates)} BD, {dates.min().date()} -> {dates.max().date()}")

    # ── PART 1: variant overlay table on XLK using TECH-bmz ──────────────────
    print("\n" + "=" * 82)
    print(" PART 1: overlay variants on XLK using TECH-bmz state (5 bps flip + 50 bps borrow)")
    print("=" * 82)
    rows = []
    for name, spec in EXTENDED_STRATEGIES.items():
        r, la, sa, n_flips = simulate(xlk_ret, tech_bmz, spec, FLIP_COST_BPS,
                                       BORROW_COST_BPS_ANNUAL)
        st = overlay_stats(r, la, sa, name, STARTING, n_flips)
        st["signal"] = "TECH_BMZ"
        rows.append(st)
    # add UNIVERSE-bmz CASH and TILT for comparison
    for name, spec in {"CASH_uni": STRATEGIES["CASH"],
                       "TILT_25_LEV_uni": EXTENDED_STRATEGIES["TILT_25_LEV"]}.items():
        r, la, sa, n_flips = simulate(xlk_ret, uni_bmz, spec, FLIP_COST_BPS,
                                       BORROW_COST_BPS_ANNUAL)
        st = overlay_stats(r, la, sa, name, STARTING, n_flips)
        st["signal"] = "UNIVERSE_BMZ"
        rows.append(st)
    tbl = pd.DataFrame(rows)
    cols = ["signal", "strategy", "total_return", "annualized_return", "sharpe",
            "max_drawdown", "ending_value"]
    with pd.option_context("display.width", 220, "display.float_format", lambda v: f"{v:+.3f}"):
        print(tbl[cols].to_string(index=False))
    tbl.to_csv(OUT_DIR / "beta_mz_tech_strategy_perf.csv", index=False)

    bh = tbl[(tbl["signal"] == "TECH_BMZ") & (tbl["strategy"] == "BH")].iloc[0]
    print(f"\n  vs XLK BH (${bh['ending_value']:,.0f}, Sharpe {bh['sharpe']:+.3f}, "
          f"DD {bh['max_drawdown']:+.3f}):")
    for s in ("CASH","HALF","LONG_SHORT_70_30","LONG_SHORT_50_50","LONG_SHORT_30_70",
              "FULL_FLIP","TILT_25_LEV"):
        r = tbl[(tbl["signal"] == "TECH_BMZ") & (tbl["strategy"] == s)].iloc[0]
        dv = r["ending_value"] - bh["ending_value"]
        ds = r["sharpe"] - bh["sharpe"]
        dd = abs(bh["max_drawdown"]) - abs(r["max_drawdown"])
        print(f"    {s:18s}: ${r['ending_value']:>11,.0f}  (Δ ${dv:>+10,.0f})  "
              f"ΔSharpe {ds:+.3f}  DDreduction {dd:+.3f}")

    # ── PART 2: holding-period sweep (cool->LONG, heat->SHORT) ───────────────
    print("\n" + "=" * 82)
    print(" PART 2: holding-period sweep on XLK (TECH-bmz events)")
    print("=" * 82)
    cool, heat = event_dates(tech_bmz)
    price = cumulative_index(xlk_ret)
    print(f"  TECH-bmz events: {len(cool)} cool, {len(heat)} heat")
    print(f"\n  {'h':>3} {'cool_n':>7} {'cool_mean':>10} {'cool_hit':>9} {'cool_Sh':>8} || "
          f"{'heat_n':>7} {'heat_mean':>10} {'heat_hit':>9} {'heat_Sh':>8}")
    sweep = []
    for h in range(21, 51, 1):
        cr = np.array([forward_window_metrics(price, d, h).get("log_ret", np.nan)
                       for d in cool])
        hr = np.array([-forward_window_metrics(price, d, h).get("log_ret", np.nan)
                       for d in heat])   # short bet -> negate
        cr = cr[np.isfinite(cr)]; hr = hr[np.isfinite(hr)]
        c_sh = cr.mean() / cr.std(ddof=1) if len(cr) > 1 and cr.std() > 0 else np.nan
        h_sh = hr.mean() / hr.std(ddof=1) if len(hr) > 1 and hr.std() > 0 else np.nan
        sweep.append({"h": h, "cool_n": len(cr), "cool_mean": cr.mean(),
                      "cool_hit": float((cr > 0).mean()), "cool_sh": c_sh,
                      "heat_n": len(hr), "heat_mean": hr.mean(),
                      "heat_hit": float((hr > 0).mean()), "heat_sh": h_sh})
    sw = pd.DataFrame(sweep)
    for h in (21, 27, 30, 35, 40, 45, 50):
        r = sw[sw["h"] == h].iloc[0]
        print(f"  {h:>3} {r['cool_n']:>7} {r['cool_mean']:>+10.3%} {r['cool_hit']:>9.0%} "
              f"{r['cool_sh']:>+8.2f} || {r['heat_n']:>7} {r['heat_mean']:>+10.3%} "
              f"{r['heat_hit']:>9.0%} {r['heat_sh']:>+8.2f}")
    bc = sw.loc[sw["cool_sh"].idxmax()]
    bh_ = sw.loc[sw["heat_sh"].idxmax()]
    print(f"\n  best cool->LONG  hold: h={int(bc['h']):2d} BD (per-bet Sharpe {bc['cool_sh']:+.2f}, "
          f"mean {bc['cool_mean']:+.2%}, hit {bc['cool_hit']:.0%})")
    print(f"  best heat->SHORT hold: h={int(bh_['h']):2d} BD (per-bet Sharpe {bh_['heat_sh']:+.2f}, "
          f"mean {bh_['heat_mean']:+.2%}, hit {bh_['heat_hit']:.0%})")
    sw.to_csv(OUT_DIR / "beta_mz_tech_strategy_holding.csv", index=False)

    # ── PART 3: spanning -- TECH-bmz vs HY and vs UNIVERSE-bmz on XLK ────────
    print("\n" + "=" * 82)
    print(" PART 3: spanning (HAC) -- does TECH-bmz CASH overlay on XLK add over...?")
    print("=" * 82)
    macro = load_macro()
    hy = add_slope_signs(hy_weekly_frame(macro), 12)
    r_tech, _ = overlay_returns(xlk_ret, calm_mask_daily(tech_bmz, dates, "slope"))
    r_hy_lv, _ = overlay_returns(xlk_ret, calm_mask_daily(hy, dates, "level"))
    r_hy_sl, _ = overlay_returns(xlk_ret, calm_mask_daily(hy, dates, "slope"))
    r_uni, _ = overlay_returns(xlk_ret, calm_mask_daily(uni_bmz, dates, "slope"))
    for label, bench in [("HY_level", r_hy_lv), ("HY_slope", r_hy_sl), ("UNIVERSE_BMZ", r_uni)]:
        s = hac_span(r_tech, bench)
        verd = ("INDEPENDENT" if s["p"] < 0.05 and s["ann_alpha"] > 0
                else "marginal" if s["p"] < 0.15 and s["ann_alpha"] > 0
                else "spanned / weaker")
        print(f"  vs {label:14s}: alpha {s['ann_alpha']:+.2%}/yr  t={s['t']:+.2f}  "
              f"p={s['p']:.3f}  IR={s['ir']:+.2f}  corr={s['corr']:+.3f}  -> {verd}")

    print("\n[BMZ_TECH] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

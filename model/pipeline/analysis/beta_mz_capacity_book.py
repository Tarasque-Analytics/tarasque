"""
beta_mz_capacity_book.py -- Reality-of-deployment tests for the cooling leg.

PART A: CAPACITY / dollar-P&L at size.
  How much AUM can the SPY cooling overlay absorb before market impact eats the
  edge? Square-root impact model calibrated so 1% of ADV ~ 5 bps. Long leg needs
  no borrow; we note the heating/short leg borrow + the VIXY tactical-variant
  capacity ceiling (VIXY ADV is tiny).

PART B: INDEPENDENCE FROM THE REST OF THE BOOK (not just HY).
  Independence from credit spreads is necessary, not sufficient. We build the
  standard book components as long/cash overlays on SPY -- equity momentum (TSMOM
  12-1), a vol-carry / low-vol proxy, the project's own VRP wedge, and HY -- then
  run a MULTIVARIATE spanning regression:
        R_cooling = a + b1*MOM + b2*VOLCARRY + b3*VRP + b4*HY + e   [HAC]
  If alpha survives controlling for ALL of them at once, the cooling leg is a
  genuinely independent slot in the book.

Outputs:
  results/validation/beta_mz_capacity.csv
  results/validation/beta_mz_book_spanning.csv
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

from ..config import load_config
from ..data_loader import ParquetStore
from .beta_mz_deep_dive import add_slope_signs, RESULTS_DIR
from .beta_mz_defensive_overlay import load_macro
from .beta_mz_drawdown_value import cumulative_index
from .beta_mz_multi_index_test import load_index_returns
from .beta_mz_panel import load_per_ticker_weekly, aggregate_subset
from .beta_mz_cooling_incremental import (
    hy_weekly_frame, calm_mask_daily, overlay_returns, sharpe_stats, START_DATE, COST_BPS,
)

OUT_DIR = RESULTS_DIR / "validation"
IMPACT_C = 50.0   # impact_bps = C*sqrt(order/ADV); 1% ADV -> 5 bps


def dollar_adv(ticker: str) -> float:
    dc, _, _ = load_config()
    oh = ParquetStore(dc.base_dir).load("ohlcv")
    oh["date"] = pd.to_datetime(oh["date"], format="mixed")
    sub = oh[(oh["ticker"] == ticker) & (oh["date"] >= START_DATE)].dropna(subset=["vol", "prc"])
    return float((sub["vol"] * sub["prc"]).median())


def aggregate_vrp_daily() -> pd.Series:
    """Mean vrp_wedge across tickers per date (h=21), as a book signal."""
    frames = []
    for f in sorted(RESULTS_DIR.glob("predictions_*.csv")):
        try:
            df = pd.read_csv(f, parse_dates=["date"], usecols=["date", "vrp_wedge", "horizon"])
        except Exception:
            continue
        h = df[df["horizon"] == 21]
        if not h.empty:
            frames.append(h[["date", "vrp_wedge"]])
    if not frames:
        return pd.Series(dtype=float)
    allv = pd.concat(frames)
    return allv.groupby("date")["vrp_wedge"].mean().sort_index()


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bmz = add_slope_signs(aggregate_subset(load_per_ticker_weekly()), 12)
    spy = load_index_returns("SPY")
    spy = spy[spy.index >= START_DATE]
    dates = spy.index
    price = cumulative_index(spy)
    bmz_calm = calm_mask_daily(bmz, dates, "slope")
    r_bmz, a_bmz = overlay_returns(spy, bmz_calm)

    # ── PART A: CAPACITY ─────────────────────────────────────────────────────
    print("=" * 80)
    print(" PART A: CAPACITY -- how much AUM can the SPY cooling overlay absorb?")
    print("=" * 80)
    spy_adv = dollar_adv("SPY")
    vixy_adv = dollar_adv("VIXY")
    n_flips = float(a_bmz.diff().abs().sum())
    n_years = (dates[-1] - dates[0]).days / 365.25
    flips_per_yr = n_flips / n_years
    print(f"  SPY median dollar ADV (2015-26): ${spy_adv/1e9:.1f}B/day")
    print(f"  overlay allocation flips: {n_flips:.0f} over {n_years:.1f}y = {flips_per_yr:.1f}/yr")
    print(f"  (long leg needs NO borrow; full 0<->1 flip trades ~AUM notional)\n")
    print(f"  {'AUM':>12} {'% of ADV':>10} {'impact/flip':>13} {'annual drag':>13}  verdict")
    rows = []
    for aum in (1e5, 1e6, 1e7, 1e8, 1e9, 1e10, 5e10):
        part = aum / spy_adv
        impact_bps = IMPACT_C * np.sqrt(min(part, 1.0))
        annual_drag_bps = impact_bps * flips_per_yr
        verdict = ("trivial" if annual_drag_bps < 10 else "manageable" if annual_drag_bps < 50
                   else "material" if annual_drag_bps < 150 else "capacity-binding")
        print(f"  ${aum/1e6:>10,.0f}M {part*100:>9.3f}% {impact_bps:>11.1f}bp "
              f"{annual_drag_bps:>11.1f}bp  {verdict}")
        rows.append({"aum": aum, "pct_adv": part, "impact_bps_per_flip": impact_bps,
                     "annual_drag_bps": annual_drag_bps, "verdict": verdict})
    print(f"\n  SPY long leg is effectively uncapacitated for any realistic AUM "
          f"(even $10B = {1e10/spy_adv*100:.1f}% of ADV).")
    print(f"  VIXY tactical-short variant ADV: ${vixy_adv/1e6:.0f}M/day -> at 10% participation "
          f"max ~${0.10*vixy_adv/1e6:.0f}M/day traded; THAT is the binding constraint, not SPY.")
    pd.DataFrame(rows).to_csv(OUT_DIR / "beta_mz_capacity.csv", index=False)

    # ── PART B: INDEPENDENCE FROM THE BOOK ───────────────────────────────────
    print("\n" + "=" * 80)
    print(" PART B: independence from the rest of the book (multivariate spanning)")
    print("=" * 80)

    # MOMENTUM (TSMOM 12-1): long when price[t-21]/price[t-252]-1 > 0
    mom_sig = (price.shift(21) / price.shift(252) - 1.0) > 0
    r_mom, _ = overlay_returns(spy, mom_sig.reindex(dates).fillna(False))

    # VOL-CARRY proxy: long when 21d realized vol <= trailing 252d median (low-vol carry)
    rv21 = spy.rolling(21).std() * np.sqrt(252)
    vc_sig = rv21 <= rv21.rolling(252, min_periods=63).median()
    r_vc, _ = overlay_returns(spy, vc_sig.reindex(dates).fillna(False))

    # VRP (project's own): long when aggregate vrp_wedge <= trailing median (low fear premium)
    vrp = aggregate_vrp_daily()
    book = {"MOM": r_mom, "VOLCARRY": r_vc}
    if not vrp.empty:
        vrp_d = vrp.reindex(dates).ffill()
        vrp_sig = vrp_d <= vrp_d.rolling(252, min_periods=63).median()
        r_vrp, _ = overlay_returns(spy, vrp_sig.fillna(False))
        book["VRP"] = r_vrp
    else:
        print("  (vrp_wedge unavailable in predictions; skipping VRP regressor)")

    # HY level overlay
    hy = add_slope_signs(hy_weekly_frame(load_macro()), 12)
    r_hy, _ = overlay_returns(spy, calm_mask_daily(hy, dates, "level"))
    book["HY"] = r_hy

    # univariate correlations + spanning alphas
    print("\n  univariate vs cooling leg:")
    span_rows = []
    for name, r in book.items():
        d = pd.concat([r_bmz.rename("y"), r.rename("x")], axis=1).dropna()
        corr = float(d["y"].corr(d["x"]))
        res = sm.OLS(d["y"].to_numpy(float),
                     sm.add_constant(d["x"].to_numpy(float))).fit(
            cov_type="HAC", cov_kwds={"maxlags": 40})
        a = float(res.params[0] * 252)
        print(f"    {name:9s}: corr {corr:+.3f}   spanning alpha {a:+.2%}/yr  "
              f"t={res.tvalues[0]:+.2f}  p={res.pvalues[0]:.3f}")
        span_rows.append({"regressor": name, "type": "univariate", "corr": corr,
                          "ann_alpha": a, "t": float(res.tvalues[0]), "p": float(res.pvalues[0])})

    # MULTIVARIATE: control for everything at once
    X = pd.concat([r.rename(n) for n, r in book.items()], axis=1)
    d = pd.concat([r_bmz.rename("y"), X], axis=1).dropna()
    Xv = sm.add_constant(d[list(book.keys())].to_numpy(float))
    res = sm.OLS(d["y"].to_numpy(float), Xv).fit(cov_type="HAC", cov_kwds={"maxlags": 40})
    ann_alpha = float(res.params[0] * 252)
    resid_vol = float(np.std(res.resid, ddof=len(book) + 1) * np.sqrt(252))
    ir = ann_alpha / resid_vol if resid_vol > 0 else np.nan
    print(f"\n  MULTIVARIATE  R_cooling = a + b*({' + '.join(book.keys())}) :")
    print(f"    alpha {ann_alpha:+.2%}/yr   t={res.tvalues[0]:+.2f}   p={res.pvalues[0]:.3f}"
          f"   IR={ir:+.2f}   (n={int(len(d))})")
    for nm, b, t in zip(book.keys(), res.params[1:], res.tvalues[1:]):
        print(f"      beta[{nm:9s}] {b:+.3f}  (t={t:+.2f})")
    verdict = ("INDEPENDENT slot in the book (alpha survives full controls)"
               if (res.pvalues[0] < 0.05 and ann_alpha > 0)
               else "marginal" if (res.pvalues[0] < 0.15 and ann_alpha > 0) else "REDUNDANT with book")
    print(f"    => {verdict}")
    span_rows.append({"regressor": "MULTIVARIATE_all", "type": "multivariate", "corr": np.nan,
                      "ann_alpha": ann_alpha, "t": float(res.tvalues[0]), "p": float(res.pvalues[0])})
    pd.DataFrame(span_rows).to_csv(OUT_DIR / "beta_mz_book_spanning.csv", index=False)
    print(f"\n[BMZ_CAPBOOK] Wrote outputs to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

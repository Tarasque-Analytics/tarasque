"""
beta_mz_per_ticker_strategy.py -- Turn the per-stock cooling signal into a
                                  tradeable strategy and stress-test its independence.

Strategy: on each per-stock cool event (W=12 slope sign-change), go LONG that name
for 40 BD. Daily portfolio = equal-weight across all currently-active longs.
Two variants:
  A) PURE: cash residual when fewer / no active longs (exposure follows signal).
  B) ALWAYS-INVESTED: SPY fallback when no active longs (more realistic overlay).

Reports Sharpe, ann return, max DD, time-in-market, ending $100k value, vs SPY BH
and equal-weight universe BH.

Then MULTIVARIATE SPANNING (HAC) of strategy daily returns on the rest of a
standard book:
  R_strategy = a + b1*HY + b2*MOMENTUM + b3*VOLCARRY + b4*UNIVERSE_BMZ + e
If a > 0 and significant -> the per-stock signal is GENUINELY INDEPENDENT (not
just an expression of HY / momentum / vol-carry / universe-bmz at the per-stock level).
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
from .beta_mz_drawdown_value import (
    load_universe_equal_weighted_index, cumulative_index, max_drawdown,
)
from .beta_mz_multi_index_test import load_index_returns
from .beta_mz_panel import load_per_ticker_weekly, aggregate_subset
from .beta_mz_cooling_incremental import (
    hy_weekly_frame, calm_mask_daily, overlay_returns, START_DATE,
)

OUT_DIR = RESULTS_DIR / "validation"
HOLD = 40
COST_BPS = 5
HAC_LAGS = 40
STARTING = 100_000


def ohlc_close() -> dict:
    dc, _, _ = load_config()
    oh = ParquetStore(dc.base_dir).load("ohlcv")
    oh["date"] = pd.to_datetime(oh["date"], format="mixed")
    return {tk: g.sort_values("date").set_index("date")["prc"].ffill()
            for tk, g in oh.drop_duplicates(["date", "ticker"]).groupby("ticker", observed=True)}


def per_stock_cool_events(panel: pd.DataFrame, w: int = 12) -> pd.DataFrame:
    rows = []
    for tk, g in panel.groupby("ticker"):
        own = g[["asof", "beta_mz"]].rename(columns={"beta_mz": "mean_bmz"}) \
                .sort_values("asof").reset_index(drop=True)
        if len(own) < w + 20:
            continue
        s = add_slope_signs(own, w)
        ev = s[s[f"sign_change_w{w}"] & (s[f"sign_lag_w{w}"] > 0) & (s[f"sign_w{w}"] < 0)]
        for _, r in ev.iterrows():
            rows.append({"ticker": tk, "asof": r["asof"]})
    return pd.DataFrame(rows)


def build_strategy(events: pd.DataFrame, prices: dict, dates: pd.DatetimeIndex,
                    spy_ret: pd.Series, hold: int, cost_bps: float, mode: str):
    """mode='pure' = cash residual; mode='deployed' = SPY fallback when no active longs."""
    # Per-ticker daily return + active mask
    rets, masks = {}, {}
    for tk in events["ticker"].unique():
        if tk not in prices:
            continue
        px = prices[tk].reindex(dates).ffill()
        rets[tk] = np.log(px / px.shift(1)).fillna(0)
        idx = dates
        mask = np.zeros(len(idx), dtype=bool)
        for d in events.loc[events["ticker"] == tk, "asof"]:
            i = idx.searchsorted(d, side="left")
            if i < len(idx):
                j = min(i + hold, len(idx) - 1)
                mask[i:j + 1] = True
        masks[tk] = pd.Series(mask, index=idx)

    ret_df = pd.DataFrame(rets).fillna(0)
    msk_df = pd.DataFrame(masks).fillna(False)
    n_active = msk_df.sum(axis=1)

    # Equal-weight across active longs
    w_per_active = (1 / n_active.replace(0, np.nan))
    active_ret = (ret_df * msk_df).sum(axis=1) * w_per_active   # daily mean of active longs
    if mode == "pure":
        strat = active_ret.fillna(0)   # cash residual (0 return) when no active
    else:   # 'deployed'
        strat = active_ret.where(n_active > 0, spy_ret.reindex(dates).fillna(0))

    # Transaction cost: per entry/exit on a ticker, charge cost_bps * weight
    weight_today = (1 / n_active.replace(0, np.nan)).fillna(1.0)
    flips = msk_df.astype(int).diff().abs().fillna(0)
    daily_turnover = flips.mul(weight_today, axis=0).sum(axis=1)
    cost_drag = daily_turnover * (cost_bps / 1e4)
    strat_net = strat - cost_drag

    return strat_net, n_active, msk_df


def stats(r: pd.Series, label: str) -> dict:
    price = cumulative_index(r) * STARTING
    n_yrs = (r.index[-1] - r.index[0]).days / 365.25
    ann_ret = float(np.exp(r.sum() / n_yrs) - 1) if n_yrs > 0 else np.nan
    ann_vol = float(r.std() * np.sqrt(252))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
    mdd, _, _ = max_drawdown(price)
    return {"strategy": label, "ann_return": ann_ret, "ann_vol": ann_vol,
            "sharpe": sharpe, "max_dd": mdd, "ending_value": float(price.iloc[-1])}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    panel = load_per_ticker_weekly()
    prices = ohlc_close()
    spy = load_index_returns("SPY")
    spy = spy[spy.index >= START_DATE]
    dates = spy.index
    ew = load_universe_equal_weighted_index()
    ew = ew.reindex(dates).fillna(0)

    events = per_stock_cool_events(panel, 12)
    print(f"[BMZ_PT_STRAT] {len(events)} per-stock cool events over "
          f"{events['ticker'].nunique()} tickers")

    # ── strategy variants ────────────────────────────────────────────────────
    r_pure, n_act, msk = build_strategy(events, prices, dates, spy, HOLD, COST_BPS, "pure")
    r_dep, _, _ = build_strategy(events, prices, dates, spy, HOLD, COST_BPS, "deployed")
    print(f"\n  avg #active longs/day: {n_act.mean():.1f}  (max {n_act.max()}, "
          f"days with 0 active: {(n_act==0).mean():.1%})")

    print("\n" + "=" * 78)
    print(" STRATEGY PERFORMANCE (2015-2026, $100k starting, 5 bps/flip)")
    print("=" * 78)
    rows = [stats(spy.reindex(dates).fillna(0), "SPY buy-and-hold"),
            stats(ew, "EW universe buy-and-hold"),
            stats(r_pure, "per-stock cool PURE (cash residual)"),
            stats(r_dep, "per-stock cool DEPLOYED (SPY fallback)")]
    sf = pd.DataFrame(rows)
    cols = ["strategy", "ann_return", "ann_vol", "sharpe", "max_dd", "ending_value"]
    with pd.option_context("display.width", 200, "display.float_format", lambda v: f"{v:+.3f}"):
        print(sf[cols].to_string(index=False))

    # ── multivariate spanning vs the book ───────────────────────────────────
    print("\n" + "=" * 78)
    print(" MULTIVARIATE SPANNING (HAC) -- does the strategy add over the book?")
    print("=" * 78)
    macro = load_macro()
    hy = add_slope_signs(hy_weekly_frame(macro), 12)
    uni = add_slope_signs(aggregate_subset(panel), 12)
    spy_price = cumulative_index(spy)
    # book components as SPY long/cash overlays (same construction as before)
    mom_sig = (spy_price.shift(21) / spy_price.shift(252) - 1.0) > 0
    rv21 = spy.rolling(21).std() * np.sqrt(252)
    vc_sig = rv21 <= rv21.rolling(252, min_periods=63).median()
    book = {
        "HY":       overlay_returns(spy, calm_mask_daily(hy, dates, "level"))[0],
        "MOM":      overlay_returns(spy, mom_sig.reindex(dates).fillna(False))[0],
        "VOLCARRY": overlay_returns(spy, vc_sig.reindex(dates).fillna(False))[0],
        "UNI_BMZ":  overlay_returns(spy, calm_mask_daily(uni, dates, "slope"))[0],
    }
    # also include EW universe to absorb any pure equity-basket beta
    book["EW_UNIVERSE"] = ew

    target = r_dep   # use the realistic DEPLOYED variant for spanning
    df = pd.concat([target.rename("strat")] + [v.rename(k) for k, v in book.items()],
                   axis=1).dropna()
    print(f"  n_obs={len(df)}, regressors: {list(book.keys())}")
    print("\n  univariate spanning of strategy vs each:")
    for name in book:
        d = df[["strat", name]].dropna()
        res = sm.OLS(d["strat"].to_numpy(float),
                     sm.add_constant(d[name].to_numpy(float))).fit(
            cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
        a = float(res.params[0] * 252)
        print(f"    vs {name:11s}: alpha {a:+.2%}/yr  t={res.tvalues[0]:+.2f}  "
              f"p={res.pvalues[0]:.3f}  corr {d.corr().iloc[0,1]:+.3f}")
    Xv = sm.add_constant(df[list(book.keys())].to_numpy(float))
    res = sm.OLS(df["strat"].to_numpy(float), Xv).fit(
        cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    ann_alpha = float(res.params[0] * 252)
    resid_vol = float(np.std(res.resid, ddof=len(book) + 1) * np.sqrt(252))
    ir = ann_alpha / resid_vol if resid_vol > 0 else np.nan
    print(f"\n  MULTIVARIATE  R_strat = a + b*({' + '.join(book.keys())}):")
    print(f"    alpha {ann_alpha:+.2%}/yr   t={res.tvalues[0]:+.2f}   p={res.pvalues[0]:.4g}   IR={ir:+.2f}")
    for nm, b, t in zip(book.keys(), res.params[1:], res.tvalues[1:]):
        print(f"      beta[{nm:11s}] {b:+.3f}  (t={t:+.2f})")
    verd = ("INDEPENDENT (alpha survives full book controls)" if (res.pvalues[0] < 0.05 and ann_alpha > 0)
            else "marginal" if (res.pvalues[0] < 0.15 and ann_alpha > 0) else "REDUNDANT with book")
    print(f"    => {verd}")

    sf.to_csv(OUT_DIR / "beta_mz_per_ticker_strategy_perf.csv", index=False)
    print("\n[BMZ_PT_STRAT] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

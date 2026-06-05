"""
beta_mz_per_ticker_battery.py -- Robustness ringer for the PER-STOCK beta_mz
                                 cooling signal (1907 events pooled, +2.0% mean,
                                 75% breadth in the prior test).

Six tests, mirroring what we did for the universe-aggregate cooling leg:

  1. INDEPENDENCE FROM UNIVERSE -- the decisive test. Per-stock cool events fire
     more often than universe events; many will coincide with the universe also
     cooling. The honest question: when the UNIVERSE is in a HEATING state, does
     the per-stock cool signal still work? If yes, it's a genuinely independent
     per-stock timing signal. If no, it's just a noisier decomposition of the
     universe regime we already validated.

  2. TEMPORAL SPLIT 2015-20 vs 2021-26.

  3. ENTRY-TIMING LADDER (FRI close / MON open / MON close / TUE open / scale-in).
     If the edge collapses moving entry one day, it's microstructure.

  4. WINDOW THRESHOLD SWEEP (4/8/10/12/14/16/24) -- plateau check.

  5. HOLDING-PERIOD SWEEP (21/30/40/50/63) -- is 40 BD also the per-stock optimum?

  6. PER-TICKER IC/RETURN DISTRIBUTION -- richer breadth than "75% positive".
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
from .beta_mz_panel import load_per_ticker_weekly, aggregate_subset

OUT_DIR = RESULTS_DIR / "validation"
HOLD = 40
SPLIT_DATE = pd.Timestamp("2020-12-31")
WINDOWS = [4, 8, 10, 12, 14, 16, 24]
HORIZONS = [21, 30, 40, 50, 63]


def load_ohlc_by_ticker() -> dict:
    dc, _, _ = load_config()
    oh = ParquetStore(dc.base_dir).load("ohlcv")
    oh["date"] = pd.to_datetime(oh["date"], format="mixed")
    out = {}
    for tk, g in oh.drop_duplicates(["date", "ticker"]).groupby("ticker", observed=True):
        out[tk] = g.sort_values("date").set_index("date")[["openprc", "prc"]].ffill()
    return out


def fwd_log_ret(close: pd.Series, d: pd.Timestamp, h: int) -> float:
    i = close.index.searchsorted(d, side="left")
    if i + h >= len(close):
        return np.nan
    p0, p1 = close.iloc[i], close.iloc[i + h]
    return float(np.log(p1 / p0)) if p0 > 0 and p1 > 0 else np.nan


def per_stock_cool_events(panel: pd.DataFrame, window: int) -> pd.DataFrame:
    """All per-stock cooling sign-change events at the given slope window."""
    out = []
    for tk, g in panel.groupby("ticker"):
        own = g[["asof", "beta_mz"]].rename(columns={"beta_mz": "mean_bmz"}) \
                .sort_values("asof").reset_index(drop=True)
        if len(own) < window + 20:
            continue
        s = add_slope_signs(own, window)
        col_lag = f"sign_lag_w{window}"; col_sign = f"sign_w{window}"; col_chg = f"sign_change_w{window}"
        ev = s[s[col_chg] & (s[col_lag] > 0) & (s[col_sign] < 0)]
        for _, r in ev.iterrows():
            out.append({"ticker": tk, "asof": r["asof"]})
    return pd.DataFrame(out)


def stats(rets: np.ndarray, label: str = "") -> dict:
    a = rets[np.isfinite(rets)]
    if len(a) < 5:
        return {"label": label, "n": int(len(a)), "mean": np.nan, "hit": np.nan, "t": np.nan}
    t = a.mean() / (a.std(ddof=1) / np.sqrt(len(a))) if a.std() > 0 else np.nan
    return {"label": label, "n": int(len(a)), "mean": float(a.mean()),
            "median": float(np.median(a)), "hit": float((a > 0).mean()), "t": float(t)}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    panel = load_per_ticker_weekly()
    ohlc = load_ohlc_by_ticker()
    print(f"[BMZ_PT_BAT] panel: {len(panel):,} rows | ohlc: {len(ohlc)} tickers")

    # canonical events at W=12
    ev12 = per_stock_cool_events(panel, 12)
    # compute forward 40-BD returns once for the canonical set
    ev12["fwd40"] = [fwd_log_ret(ohlc[tk]["prc"], d, HOLD) if tk in ohlc else np.nan
                     for tk, d in zip(ev12["ticker"], ev12["asof"])]
    print(f"  canonical W=12 per-stock COOL events: {len(ev12)}  "
          f"(with forward 40d ret: {ev12['fwd40'].notna().sum()})")

    # ── TEST 1: INDEPENDENCE FROM THE UNIVERSE ───────────────────────────────
    print("\n" + "=" * 80)
    print(" TEST 1: does the per-stock cool signal work when the UNIVERSE is HEATING?")
    print("=" * 80)
    uni = add_slope_signs(aggregate_subset(panel), 12)
    uni_sign = uni.set_index("asof")["sign_w12"].sort_index()
    ev12["uni_sign"] = uni_sign.reindex(ev12["asof"], method="ffill").values
    agree = ev12[ev12["uni_sign"] <= 0]    # universe also cooling (sign <= 0)
    disag = ev12[ev12["uni_sign"] > 0]     # universe in heating state
    print(f"  {len(agree)} events when universe ALSO cooling | "
          f"{len(disag)} events when universe in HEATING state")
    for label, sub in [("universe agrees (also cooling)", agree),
                       ("universe DISAGREES (heating)", disag)]:
        r = stats(sub["fwd40"].to_numpy(float), label)
        print(f"  {label:34s}: n={r['n']:4d}  mean {r['mean']:+.3%}  "
              f"hit {r['hit']:.0%}  naive t {r['t']:+.2f}")

    # ── TEST 2: TEMPORAL SPLIT ───────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" TEST 2: TEMPORAL SPLIT 2015-2020 vs 2021-2026")
    print("=" * 80)
    for label, sub in [("2015-2020", ev12[ev12["asof"] <= SPLIT_DATE]),
                       ("2021-2026", ev12[ev12["asof"] > SPLIT_DATE])]:
        r = stats(sub["fwd40"].to_numpy(float), label)
        bd = sub.groupby("ticker")["fwd40"].mean()
        breadth = float((bd > 0).mean()) if len(bd) else np.nan
        print(f"  {label}: n={r['n']:4d}  mean {r['mean']:+.3%}  hit {r['hit']:.0%}  "
              f"naive t {r['t']:+.2f}  breadth {breadth:.0%} of {len(bd)} tickers")

    # ── TEST 3: ENTRY-TIMING LADDER ──────────────────────────────────────────
    print("\n" + "=" * 80)
    print(f" TEST 3: entry-timing ladder (exit fixed at close FRI+{HOLD} BD)")
    print("=" * 80)
    conv_rets = {k: [] for k in ("FRI_CLOSE", "MON_OPEN", "MON_CLOSE", "TUE_OPEN", "SCALE_3D")}
    for tk, d in zip(ev12["ticker"], ev12["asof"]):
        if tk not in ohlc:
            continue
        df = ohlc[tk]
        i = df.index.searchsorted(d, "right") - 1
        if i < 0 or i + HOLD >= len(df) or i + 3 >= len(df):
            continue
        exit_px = df["prc"].iloc[i + HOLD]
        entries = {"FRI_CLOSE": df["prc"].iloc[i],
                   "MON_OPEN": df["openprc"].iloc[i + 1],
                   "MON_CLOSE": df["prc"].iloc[i + 1],
                   "TUE_OPEN": df["openprc"].iloc[i + 2],
                   "SCALE_3D": np.mean([df["openprc"].iloc[i + 1],
                                          df["openprc"].iloc[i + 2],
                                          df["openprc"].iloc[i + 3]])}
        for k, ep in entries.items():
            conv_rets[k].append(float(np.log(exit_px / ep)) if ep > 0 and exit_px > 0 else np.nan)
    base = stats(np.array(conv_rets["FRI_CLOSE"]), "FRI_CLOSE")
    for k in ("FRI_CLOSE", "MON_OPEN", "MON_CLOSE", "TUE_OPEN", "SCALE_3D"):
        r = stats(np.array(conv_rets[k]), k)
        tax = base["mean"] - r["mean"]
        print(f"  {k:10s}: n={r['n']:4d}  mean {r['mean']:+.3%}  hit {r['hit']:.0%}  "
              f"per-bet t {r['t']:+.2f}  tax vs FRI {tax:+.3%}")

    # ── TEST 4: WINDOW THRESHOLD SWEEP ───────────────────────────────────────
    print("\n" + "=" * 80)
    print(" TEST 4: window threshold sweep on per-stock signal (40-BD hold)")
    print("=" * 80)
    rows4 = []
    for w in WINDOWS:
        ev = per_stock_cool_events(panel, w)
        ev["fwd40"] = [fwd_log_ret(ohlc[tk]["prc"], d, HOLD) if tk in ohlc else np.nan
                       for tk, d in zip(ev["ticker"], ev["asof"])]
        r = stats(ev["fwd40"].to_numpy(float), f"w{w}")
        bd = ev.groupby("ticker")["fwd40"].mean()
        breadth = float((bd > 0).mean()) if len(bd) else np.nan
        rows4.append({"window": w, "n_events": r["n"], "mean": r["mean"],
                      "hit": r["hit"], "t": r["t"], "breadth": breadth})
        print(f"  w={w:2d}: n={r['n']:4d}  mean {r['mean']:+.3%}  hit {r['hit']:.0%}  "
              f"t {r['t']:+.2f}  breadth {breadth:.0%}")

    # ── TEST 5: HOLDING-PERIOD SWEEP ─────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" TEST 5: holding-period sweep (W=12 events, varied hold)")
    print("=" * 80)
    rows5 = []
    for h in HORIZONS:
        rets = np.array([fwd_log_ret(ohlc[tk]["prc"], d, h) if tk in ohlc else np.nan
                         for tk, d in zip(ev12["ticker"], ev12["asof"])])
        r = stats(rets, f"h{h}")
        per_h_per_t = mean_per_signal_per_day = r["mean"] / h * 252
        rows5.append({"hold_bd": h, "n": r["n"], "mean": r["mean"], "hit": r["hit"],
                      "t": r["t"], "annualized_rate": per_h_per_t})
        print(f"  hold={h:2d} BD: n={r['n']:4d}  mean {r['mean']:+.3%}  hit {r['hit']:.0%}  "
              f"t {r['t']:+.2f}  ann.rate {per_h_per_t*100:+.1f}%")
    best = max(rows5, key=lambda r: r["t"])
    print(f"  best risk-adj hold: {best['hold_bd']} BD (t={best['t']:+.2f})")

    # ── TEST 6: PER-TICKER DISTRIBUTION ──────────────────────────────────────
    print("\n" + "=" * 80)
    print(" TEST 6: per-ticker distribution (the honest breadth)")
    print("=" * 80)
    pt = ev12.groupby("ticker")["fwd40"].agg(["count", "mean", "std"]).rename(
        columns={"count": "n"})
    pt["t"] = pt["mean"] / (pt["std"] / np.sqrt(pt["n"]))
    pt = pt[pt["n"] >= 3]
    print(f"  {len(pt)} tickers with >=3 events")
    print(f"  per-ticker mean:    median {pt['mean'].median():+.3%}  "
          f"p25 {pt['mean'].quantile(.25):+.3%}  p75 {pt['mean'].quantile(.75):+.3%}")
    print(f"  per-ticker t-stat:  median {pt['t'].median():+.2f}  "
          f"p25 {pt['t'].quantile(.25):+.2f}  p75 {pt['t'].quantile(.75):+.2f}")
    print(f"  breadth: {(pt['mean']>0).mean():.0%} positive mean  | "
          f"{(pt['t']>1).mean():.0%} per-ticker t>1  | "
          f"{(pt['t']>2).mean():.0%} per-ticker t>2  | "
          f"{(pt['t']<-1).mean():.0%} per-ticker t<-1")
    pt.to_csv(OUT_DIR / "beta_mz_per_ticker_battery.csv")
    print("\n[BMZ_PT_BAT] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

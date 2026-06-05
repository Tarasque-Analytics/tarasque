"""
beta_mz_slope_conditional.py -- Slope-MAGNITUDE conditional signals + the "flat
                                regime" question.

Two problems with the current zero-crossing signal:
  (1) Sign-changes of slope_w12 strictly ALTERNATE by construction -- you can never
      get two consecutive cooling signals, even when the slope dips shallowly and
      re-steepens in the same direction.
  (2) Near-zero crossings are noise -> whipsaws (up, down, up in quick succession).

Fix tested here: condition on slope MAGNITUDE, not just its sign.

PART A -- MAGNITUDE BUCKETS: bucket weeks by signed slope (steep-cool ... flat ...
  steep-heat) and report forward 21/42-BD SPY return, vol, max DD. Answers "what
  does a FLAT beta_mz curve mean for forward {return, vol, drawdown}" and whether
  conviction (|slope|) adds over sign.

PART B -- DEADBAND / HYSTERESIS overlay (Schmitt trigger):
  long when slope <= -T (confirmed cooling); cash when slope >= +T (confirmed
  heating); HOLD previous state in the flat band |slope| < T. Sweep T; compare
  Sharpe + whipsaw count vs the T=0 zero-cross baseline.

PART C -- CONSECUTIVE SAME-SORT signals: with a deadband, threshold-cross events
  can repeat in the same direction. Count them and check whether a reinforcing
  2nd cooling confirm is followed by good returns.

PART D -- |slope| as a CONVICTION GATE: does requiring |slope|>T at the cooling
  signal improve the per-bet edge?

Output: results/validation/beta_mz_slope_conditional_*.csv
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

from .beta_mz_deep_dive import add_slope_signs, load_spy_vol
from .beta_mz_drawdown_value import cumulative_index, forward_window_metrics
from .beta_mz_multi_index_test import load_index_returns
from .beta_mz_panel import load_per_ticker_weekly, aggregate_subset
from .beta_mz_cooling_incremental import overlay_returns, sharpe_stats, START_DATE

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "validation"
HOLD_BD = 40
FWD = (21, 42)


def fwd_vol(spy_vol, d, h):
    i = spy_vol.index.searchsorted(d, "left")
    return float(spy_vol.iloc[i:i + h].max()) if i + h < len(spy_vol) else np.nan


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bmz = add_slope_signs(aggregate_subset(load_per_ticker_weekly()), 12)
    spy = load_index_returns("SPY")
    spy = spy[spy.index >= START_DATE]
    dates = spy.index
    price = cumulative_index(spy)
    spy_vol = load_spy_vol()
    slope_w = bmz.dropna(subset=["slope_w12"]).copy()
    s_abs = slope_w["slope_w12"].abs()
    print(f"[BMZ_COND] slope_w12: std={slope_w['slope_w12'].std():.4f}  "
          f"|slope| median={s_abs.median():.4f}  p33={s_abs.quantile(.33):.4f}  "
          f"p66={s_abs.quantile(.66):.4f}")

    # ── PART A: MAGNITUDE BUCKETS ────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" PART A: forward outcomes by signed-slope bucket (the 'flat' question)")
    print("=" * 80)
    wk = slope_w[slope_w["asof"] >= START_DATE].copy()
    for h in FWD:
        wk[f"fwd_ret_{h}"] = wk["asof"].apply(
            lambda d: forward_window_metrics(price, d, h).get("log_ret", np.nan))
        wk[f"fwd_dd_{h}"] = wk["asof"].apply(
            lambda d: forward_window_metrics(price, d, h).get("max_dd", np.nan))
        wk[f"fwd_vol_{h}"] = wk["asof"].apply(lambda d: fwd_vol(spy_vol, d, h))
    wk = wk.dropna(subset=["fwd_ret_42"])
    wk["bucket"] = pd.qcut(wk["slope_w12"], 5,
                           labels=["steep_COOL", "mild_cool", "FLAT", "mild_heat", "steep_HEAT"])
    agg = wk.groupby("bucket", observed=True).agg(
        n=("slope_w12", "size"),
        slope_mean=("slope_w12", "mean"),
        ret42_mean=("fwd_ret_42", "mean"),
        ret42_hit=("fwd_ret_42", lambda s: float((s > 0).mean())),
        vol42_mean=("fwd_vol_42", "mean"),
        dd42_mean=("fwd_dd_42", "mean"),
    ).reset_index()
    with pd.option_context("display.width", 200, "display.float_format", lambda v: f"{v:+.3f}"):
        print(agg.to_string(index=False))
    # explicit flat-vs-rest using |slope| terciles
    wk["mag"] = pd.qcut(s_abs.reindex(wk.index), 3, labels=["FLAT", "mild", "STEEP"])
    flat = wk[wk["mag"] == "FLAT"]
    print(f"\n  FLAT band (|slope| bottom tercile, n={len(flat)}): "
          f"fwd_ret_42 {flat['fwd_ret_42'].mean():+.2%} (hit {float((flat['fwd_ret_42']>0).mean()):.0%})  "
          f"fwd_vol_42 {flat['fwd_vol_42'].mean():.3f}  fwd_dd_42 {flat['fwd_dd_42'].mean():+.2%}")
    print(f"  all-weeks baseline:           "
          f"fwd_ret_42 {wk['fwd_ret_42'].mean():+.2%} (hit {float((wk['fwd_ret_42']>0).mean()):.0%})  "
          f"fwd_vol_42 {wk['fwd_vol_42'].mean():.3f}  fwd_dd_42 {wk['fwd_dd_42'].mean():+.2%}")
    agg.to_csv(OUT_DIR / "beta_mz_slope_conditional_buckets.csv", index=False)

    # ── PART B: DEADBAND / HYSTERESIS overlay ────────────────────────────────
    print("\n" + "=" * 80)
    print(" PART B: deadband/hysteresis overlay vs zero-cross baseline (SPY)")
    print("  long when slope<=-T ; cash when slope>=+T ; hold in flat band |slope|<T")
    print("=" * 80)
    slope_daily = slope_w.set_index("asof")["slope_w12"].sort_index().reindex(dates, method="ffill")
    T_grid = [0.0, s_abs.quantile(0.25), s_abs.quantile(0.40),
              s_abs.quantile(0.50), s_abs.quantile(0.66)]
    rows = []
    for T in T_grid:
        # hysteresis state machine
        state = np.nan
        alloc = np.zeros(len(slope_daily))
        sv = slope_daily.to_numpy(float)
        for i, x in enumerate(sv):
            if np.isfinite(x):
                if x <= -T:
                    state = 1.0
                elif x >= T:
                    state = 0.0
                # else hold
            alloc[i] = state if np.isfinite(state) else 0.0
        alloc_s = pd.Series(alloc, index=dates)
        r, a = overlay_returns(spy, alloc_s.astype(bool) if T == 0 else (alloc_s > 0.5))
        # use continuous alloc directly for cost/return
        cost = alloc_s.diff().abs().fillna(0) * (5 / 1e4)
        rr = spy * alloc_s - cost
        st = sharpe_stats(rr, alloc_s, f"T={T:.4f}")
        n_flips = float(alloc_s.diff().abs().sum())
        # whipsaws = round trips shorter than 21 BD
        chg = alloc_s.diff().fillna(0)
        flip_idx = np.where(chg.to_numpy() != 0)[0]
        whips = int(np.sum(np.diff(flip_idx) < 21)) if len(flip_idx) > 1 else 0
        rows.append({"T": T, "sharpe": st["sharpe"], "ann_return": st["ann_return"],
                     "max_dd": st["max_drawdown"], "time_in_mkt": st["time_in_market"],
                     "n_flips": n_flips, "whipsaws_lt21bd": whips})
    db = pd.DataFrame(rows)
    with pd.option_context("display.width", 200, "display.float_format", lambda v: f"{v:+.4f}"):
        print(db.to_string(index=False))
    base = db.iloc[0]
    best = db.loc[db["sharpe"].idxmax()]
    print(f"\n  baseline (T=0): Sharpe {base['sharpe']:+.3f}, {base['n_flips']:.0f} flips, "
          f"{base['whipsaws_lt21bd']:.0f} whipsaws")
    print(f"  best deadband (T={best['T']:.4f}): Sharpe {best['sharpe']:+.3f}, "
          f"{best['n_flips']:.0f} flips, {best['whipsaws_lt21bd']:.0f} whipsaws")
    db.to_csv(OUT_DIR / "beta_mz_slope_conditional_deadband.csv", index=False)

    # magnitude-SCALED (continuous) long-only overlay: more long when steeper cool
    scale = s_abs.quantile(0.66)
    cont_alloc = (-slope_daily / scale).clip(0, 1)   # 0 when heating, up to 1 when steep cool
    cost = cont_alloc.diff().abs().fillna(0) * (5 / 1e4)
    rc = spy * cont_alloc - cost
    sc = sharpe_stats(rc, cont_alloc, "scaled")
    print(f"  magnitude-SCALED long-only: Sharpe {sc['sharpe']:+.3f}  ret {sc['ann_return']:+.2%}  "
          f"DD {sc['max_drawdown']:+.2%}  avg-alloc {cont_alloc.mean():.2f}")

    # ── PART C: CONSECUTIVE SAME-SORT signals (deadband threshold crossings) ──
    print("\n" + "=" * 80)
    print(" PART C: consecutive same-sort signals enabled by a deadband")
    print("=" * 80)
    T = s_abs.quantile(0.50)
    sw = slope_w.sort_values("asof").reset_index(drop=True)
    sv = sw["slope_w12"].to_numpy()
    events = []   # (date, 'cool'|'heat')
    armed = None  # last confirmed direction
    for i in range(len(sv)):
        if sv[i] <= -T and armed != "cool_band":
            # crossing into cool band from outside
            pass
    # simpler: detect crossings into each band
    in_cool = sv <= -T
    in_heat = sv >= T
    last = None
    for i in range(len(sv)):
        if in_cool[i] and (i == 0 or not in_cool[i - 1]):
            events.append((sw["asof"][i], "cool"))
        elif in_heat[i] and (i == 0 or not in_heat[i - 1]):
            events.append((sw["asof"][i], "heat"))
    ev = pd.DataFrame(events, columns=["asof", "kind"])
    # consecutive same-sort = kind equals previous kind
    ev["prev"] = ev["kind"].shift(1)
    ev["consecutive_same"] = ev["kind"] == ev["prev"]
    n_cool = int((ev["kind"] == "cool").sum())
    n_consec_cool = int(((ev["kind"] == "cool") & ev["consecutive_same"]).sum())
    print(f"  T={T:.4f} band crossings: {len(ev)} total, {n_cool} cool, "
          f"{n_consec_cool} of which are CONSECUTIVE cool (impossible under zero-cross)")
    # value of a reinforcing 2nd+ cool confirm vs a first cool confirm
    for label, mask in [("first cool confirm", (ev["kind"] == "cool") & ~ev["consecutive_same"]),
                        ("reinforcing cool confirm", (ev["kind"] == "cool") & ev["consecutive_same"])]:
        rets = [forward_window_metrics(price, d, HOLD_BD).get("log_ret", np.nan)
                for d in ev[mask]["asof"]]
        rets = [r for r in rets if np.isfinite(r)]
        if rets:
            print(f"    {label:26s}: n={len(rets):2d}  fwd_40bd {np.mean(rets):+.2%}  "
                  f"hit {float(np.mean(np.array(rets)>0)):.0%}")
    ev.to_csv(OUT_DIR / "beta_mz_slope_conditional_events.csv", index=False)

    # ── PART D: |slope| CONVICTION GATE on the cooling signal ────────────────
    print("\n" + "=" * 80)
    print(" PART D: |slope| conviction gate -- cooling events split by slope steepness")
    print("=" * 80)
    cool_ev = bmz[bmz["sign_change_w12"] & (bmz["sign_lag_w12"] > 0) & (bmz["sign_w12"] < 0)].copy()
    cool_ev["abs_slope"] = cool_ev["slope_w12"].abs()
    med = cool_ev["abs_slope"].median()
    for label, sub in [("STEEP cooling (|slope|>=median)", cool_ev[cool_ev["abs_slope"] >= med]),
                       ("SHALLOW cooling (|slope|<median)", cool_ev[cool_ev["abs_slope"] < med])]:
        rets = [forward_window_metrics(price, d, HOLD_BD).get("log_ret", np.nan)
                for d in sub["asof"]]
        rets = [r for r in rets if np.isfinite(r)]
        if rets:
            a = np.array(rets)
            print(f"  {label:34s}: n={len(a):2d}  fwd_40bd {a.mean():+.2%}  "
                  f"hit {float(np.mean(a>0)):.0%}  per-bet Sharpe "
                  f"{a.mean()/a.std(ddof=1) if len(a)>1 and a.std()>0 else float('nan'):+.2f}")
    print(f"\n[BMZ_COND] Wrote 3 CSVs to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

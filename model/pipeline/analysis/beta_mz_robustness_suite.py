"""
beta_mz_robustness_suite.py -- Falsification + mechanism battery on the COOLING leg.

Tests (all on the universe-mean beta_mz cooling overlay, SPY unless noted):
  1. TEMPORAL SPLIT of the spanning alpha vs HY: 2015-2020 vs 2021-2026.
     Does the +6% incremental alpha survive in BOTH halves, or is it one regime?
  3. WINDOW THRESHOLD SWEEP: Sharpe at slope windows 4/8/10/11/12/13/14/16/24.
     Want a PLATEAU around 12, not a spike (a spike = overfit window).
  4. SUB-ENSEMBLE STABILITY: rebuild the signal on random K-of-93 model subsets
     (K=50,30,15). If it survives random subsets, the "dozens-of-models-agree"
     thesis is real; if it needs specific models, it's fragile.
  5. DISPERSION vs LEVEL: does cross-stock beta_mz DISPERSION (do the models
     agree?) add over the mean? The mechanism story is about dispersion, not just
     the mean moving -- so test whether we're leaving the better feature on the table.
  7. MID-HOLD OVERRIDE: live rule = a new (heating) signal during a 40-BD long hold
     forces an immediate exit. Confirm the override never hurt in-sample.

Uses the cached per-ticker panel (beta_mz_panel) + overlay machinery
(beta_mz_cooling_incremental).
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

from .beta_mz_deep_dive import add_slope_signs, load_spy_vol
from .beta_mz_defensive_overlay import load_macro
from .beta_mz_drawdown_value import cumulative_index, forward_window_metrics
from .beta_mz_multi_index_test import load_index_returns
from .beta_mz_panel import load_per_ticker_weekly, aggregate_subset
from .beta_mz_cooling_incremental import (
    hy_weekly_frame, calm_mask_daily, overlay_returns, sharpe_stats,
    START_DATE, HOLD_BD, COST_BPS,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "validation"
SPLIT_DATE = pd.Timestamp("2020-12-31")
HAC_LAGS = 40


def span(y_ser: pd.Series, x_ser: pd.Series, lags: int = HAC_LAGS) -> dict:
    d = pd.concat([y_ser.rename("y"), x_ser.rename("x")], axis=1).dropna()
    yv = d["y"].to_numpy(float)
    xv = sm.add_constant(d["x"].to_numpy(float))
    res = sm.OLS(yv, xv).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    ann_a = float(res.params[0] * 252)
    resid_vol = float(np.std(res.resid, ddof=2) * np.sqrt(252))
    return {"ann_alpha": ann_a, "t": float(res.tvalues[0]), "p": float(res.pvalues[0]),
            "beta": float(res.params[1]), "ir": ann_a / resid_vol if resid_vol > 0 else np.nan,
            "n": int(len(d))}


def cooling_events(signed: pd.DataFrame) -> list:
    ev = signed[signed["sign_change_w12"] & (signed["sign_lag_w12"] > 0)
                & (signed["sign_w12"] < 0)]
    return ev["asof"].sort_values().tolist()


def all_signchange_events(signed: pd.DataFrame, w: int = 12) -> pd.DataFrame:
    ev = signed[signed[f"sign_change_w{w}"]].copy()
    ev["dir"] = np.where((ev[f"sign_lag_w{w}"] > 0) & (ev[f"sign_w{w}"] < 0), "cooling",
                  np.where((ev[f"sign_lag_w{w}"] < 0) & (ev[f"sign_w{w}"] > 0), "heating", ""))
    return ev[ev["dir"] != ""][["asof", "dir"]].sort_values("asof").reset_index(drop=True)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    panel = load_per_ticker_weekly()
    all_tickers = sorted(panel["ticker"].unique())
    agg_full = aggregate_subset(panel)
    bmz = add_slope_signs(agg_full, 12)
    macro = load_macro()
    hy = add_slope_signs(hy_weekly_frame(macro), 12)
    spy = load_index_returns("SPY")
    spy = spy[spy.index >= START_DATE]
    dates = spy.index
    price = cumulative_index(spy)
    r_bmz, _ = overlay_returns(spy, calm_mask_daily(bmz, dates, "slope"))

    # ── TEST 1: TEMPORAL SPLIT of spanning alpha ─────────────────────────────
    print("=" * 80)
    print(" TEST 1: TEMPORAL SPLIT of cooling-leg spanning alpha vs HY")
    print("  full-sample was +6.1% (slope) / +6.6% (level), p<0.02")
    print("=" * 80)
    rows1 = []
    for hy_mode, label in [("slope", "HY_slope"), ("level", "HY_level")]:
        r_hy, _ = overlay_returns(spy, calm_mask_daily(hy, dates, hy_mode))
        for half, msk in [("2015-2020", dates <= SPLIT_DATE), ("2021-2026", dates > SPLIT_DATE)]:
            s = span(r_bmz[msk], r_hy[msk])
            print(f"  {label} | {half}: alpha {s['ann_alpha']:+.2%}/yr  t={s['t']:+.2f}  "
                  f"p={s['p']:.3f}  IR={s['ir']:+.2f}  (n={s['n']})")
            rows1.append({"benchmark": label, "half": half, **s})
    pd.DataFrame(rows1).to_csv(OUT_DIR / "beta_mz_rob_temporal_split.csv", index=False)

    # ── TEST 3: WINDOW THRESHOLD SWEEP ───────────────────────────────────────
    print("\n" + "=" * 80)
    print(" TEST 3: WINDOW THRESHOLD SWEEP (cooling overlay Sharpe vs slope window)")
    print("  want a PLATEAU around 12, not a spike")
    print("=" * 80)
    rows3 = []
    for w in [4, 8, 10, 11, 12, 13, 14, 16, 24]:
        bw = add_slope_signs(agg_full, w)
        sign = bw.set_index("asof")[f"sign_w{w}"].sort_index().reindex(dates, method="ffill")
        calm = (sign <= 0)
        r, a = overlay_returns(spy, calm)
        st = sharpe_stats(r, a, f"w{w}")
        # per-event cooling 40-BD return
        ev = bw[bw[f"sign_change_w{w}"] & (bw[f"sign_lag_w{w}"] > 0) & (bw[f"sign_w{w}"] < 0)]
        rets = [forward_window_metrics(price, d, HOLD_BD).get("log_ret", np.nan)
                for d in ev["asof"]]
        rets = [r for r in rets if np.isfinite(r)]
        rows3.append({"window_w": w, "sharpe": st["sharpe"], "max_dd": st["max_drawdown"],
                      "time_in_mkt": st["time_in_market"], "n_cool_events": len(rets),
                      "cool_evt_mean_40bd": float(np.mean(rets)) if rets else np.nan})
    sweep = pd.DataFrame(rows3)
    with pd.option_context("display.width", 200, "display.float_format", lambda v: f"{v:+.3f}"):
        print(sweep.to_string(index=False))
    sweep.to_csv(OUT_DIR / "beta_mz_rob_window_sweep.csv", index=False)
    core = sweep[sweep["window_w"].isin([10, 11, 12, 13, 14])]["sharpe"]
    print(f"  core window 10-14 Sharpe range: {core.min():.3f}-{core.max():.3f}  "
          f"(spread {core.max()-core.min():.3f}) -> "
          f"{'PLATEAU (robust)' if core.max()-core.min() < 0.20 else 'SPIKY (overfit risk)'}")

    # ── TEST 4: SUB-ENSEMBLE STABILITY ───────────────────────────────────────
    print("\n" + "=" * 80)
    print(" TEST 4: SUB-ENSEMBLE STABILITY (signal on random K-of-93 models)")
    print("  if it survives random subsets, 'dozens-of-models-agree' thesis is real")
    print("=" * 80)
    rng = np.random.default_rng(7)
    full_mean = bmz.set_index("asof")["mean_bmz"]
    rows4 = []
    B = 50
    for K in [93, 50, 30, 15]:
        sharpes, corrs = [], []
        draws = 1 if K == 93 else B
        for _ in range(draws):
            tks = all_tickers if K == 93 else list(rng.choice(all_tickers, K, replace=False))
            aw = add_slope_signs(aggregate_subset(panel, tks), 12)
            sign = aw.set_index("asof")["sign_w12"].sort_index().reindex(dates, method="ffill")
            r, a = overlay_returns(spy, (sign <= 0))
            sharpes.append(sharpe_stats(r, a, "x")["sharpe"])
            corrs.append(float(aw.set_index("asof")["mean_bmz"].corr(full_mean)))
        sharpes = np.array(sharpes)
        print(f"  K={K:2d}: Sharpe mean {sharpes.mean():+.3f}  "
              f"p5 {np.percentile(sharpes,5):+.3f}  p95 {np.percentile(sharpes,95):+.3f}  "
              f"| mean corr w/ full agg {np.mean(corrs):+.3f}  (draws={draws})")
        rows4.append({"K": K, "sharpe_mean": float(sharpes.mean()),
                      "sharpe_p5": float(np.percentile(sharpes, 5)),
                      "sharpe_p95": float(np.percentile(sharpes, 95)),
                      "mean_corr_full": float(np.mean(corrs)), "draws": draws})
    pd.DataFrame(rows4).to_csv(OUT_DIR / "beta_mz_rob_subensemble.csv", index=False)

    # ── TEST 5: DISPERSION vs LEVEL ──────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" TEST 5: DISPERSION (cross-stock std beta_mz) vs the MEAN")
    print("=" * 80)
    spy_vol = load_spy_vol()
    disp_frame = agg_full[["asof", "std_bmz"]].rename(columns={"std_bmz": "mean_bmz"})
    disp = add_slope_signs(disp_frame, 12)
    # IC of dispersion level & slope vs forward SPY vol + return
    tmp = disp.dropna(subset=["mean_bmz", "slope_w12"]).copy()
    tmp["fwd_vol42"] = tmp["asof"].apply(
        lambda d: float(spy_vol.iloc[spy_vol.index.searchsorted(d, "left"):
                        spy_vol.index.searchsorted(d, "left") + 42].max())
        if spy_vol.index.searchsorted(d, "left") + 42 < len(spy_vol) else np.nan)
    tmp["fwd_ret42"] = tmp["asof"].apply(
        lambda d: forward_window_metrics(price, d, 42).get("log_ret", np.nan))
    tt = tmp.dropna(subset=["fwd_vol42", "fwd_ret42"])
    print(f"  IC(disp LEVEL, fwd_vol42): {tt['mean_bmz'].corr(tt['fwd_vol42'],method='spearman'):+.3f}"
          f"   IC(disp SLOPE, fwd_vol42): {tt['slope_w12'].corr(tt['fwd_vol42'],method='spearman'):+.3f}")
    print(f"  IC(disp LEVEL, fwd_ret42): {tt['mean_bmz'].corr(tt['fwd_ret42'],method='spearman'):+.3f}"
          f"   IC(disp SLOPE, fwd_ret42): {tt['slope_w12'].corr(tt['fwd_ret42'],method='spearman'):+.3f}")
    # dispersion standalone overlays (both directions) + incremental over mean
    dsign = disp.set_index("asof")["sign_w12"].sort_index().reindex(dates, method="ffill")
    r_disp_falling, a1 = overlay_returns(spy, (dsign <= 0))   # long when dispersion falling (agreement rising)
    r_disp_rising, a2 = overlay_returns(spy, (dsign > 0))     # long when dispersion rising
    print(f"  dispersion overlay -- long when disp FALLING: Sharpe "
          f"{sharpe_stats(r_disp_falling,a1,'x')['sharpe']:+.3f}  "
          f"(in-mkt {a1.mean():.0%})")
    print(f"  dispersion overlay -- long when disp RISING : Sharpe "
          f"{sharpe_stats(r_disp_rising,a2,'x')['sharpe']:+.3f}  (in-mkt {a2.mean():.0%})")
    best_disp = r_disp_falling if sharpe_stats(r_disp_falling, a1, "x")["sharpe"] >= \
        sharpe_stats(r_disp_rising, a2, "x")["sharpe"] else r_disp_rising
    s_dm = span(r_bmz, best_disp)   # does MEAN add over dispersion?
    s_md = span(best_disp, r_bmz)   # does DISPERSION add over mean?
    print(f"  spanning  MEAN-overlay on DISP-overlay: alpha {s_dm['ann_alpha']:+.2%}/yr "
          f"t={s_dm['t']:+.2f} p={s_dm['p']:.3f}  (mean adds over dispersion?)")
    print(f"  spanning  DISP-overlay on MEAN-overlay: alpha {s_md['ann_alpha']:+.2%}/yr "
          f"t={s_md['t']:+.2f} p={s_md['p']:.3f}  (dispersion adds over mean?)")
    pd.DataFrame([{"test": "mean_over_disp", **s_dm},
                  {"test": "disp_over_mean", **s_md}]).to_csv(
        OUT_DIR / "beta_mz_rob_dispersion.csv", index=False)

    # ── TEST 7: MID-HOLD OVERRIDE ────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" TEST 7: MID-HOLD OVERRIDE rule (new heating signal during long hold -> exit)")
    print("=" * 80)
    sc = all_signchange_events(bmz, 12)
    gaps = sc["asof"].diff().dropna().dt.days / 1.4  # ~BD
    print(f"  {len(sc)} sign-change events | min gap ~{gaps.min():.0f} BD  "
          f"median ~{gaps.median():.0f} BD  (hold={HOLD_BD} BD -> overlaps exist if min<{HOLD_BD})")
    cool_ev = cooling_events(bmz)
    # Rule A: hold full 40 BD from each cooling event
    maskA = pd.Series(False, index=dates)
    for d in cool_ev:
        i = dates.searchsorted(d, "left")
        if i < len(dates):
            maskA.iloc[i:min(i + HOLD_BD, len(dates) - 1) + 1] = True
    # Rule B: same, but truncate at the next heating event
    heat_dates = sc[sc["dir"] == "heating"]["asof"].tolist()
    maskB = pd.Series(False, index=dates)
    for d in cool_ev:
        i = dates.searchsorted(d, "left")
        if i >= len(dates):
            continue
        end = min(i + HOLD_BD, len(dates) - 1)
        nxt = [h for h in heat_dates if h > d]
        if nxt:
            j = dates.searchsorted(nxt[0], "left")
            end = min(end, max(i, j - 1))
        maskB.iloc[i:end + 1] = True
    rA, aA = overlay_returns(spy, maskA)
    rB, aB = overlay_returns(spy, maskB)
    sA = sharpe_stats(rA, aA, "hold_full_40bd")
    sB = sharpe_stats(rB, aB, "override_on_heating")
    print(f"  Rule A hold-full-40BD : Sharpe {sA['sharpe']:+.3f}  ret {sA['ann_return']:+.2%}  "
          f"DD {sA['max_drawdown']:+.2%}  in-mkt {sA['time_in_market']:.0%}")
    print(f"  Rule B override-exit  : Sharpe {sB['sharpe']:+.3f}  ret {sB['ann_return']:+.2%}  "
          f"DD {sB['max_drawdown']:+.2%}  in-mkt {sB['time_in_market']:.0%}")
    delta = (rB - rA).sum()
    print(f"  cumulative log-return diff (override - hold): {delta:+.4f}  -> "
          f"{'override helped / neutral' if delta >= -0.01 else 'override HURT'}")
    pd.DataFrame([sA, sB]).to_csv(OUT_DIR / "beta_mz_rob_override.csv", index=False)

    print(f"\n[BMZ_ROB] Wrote 5 CSVs to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

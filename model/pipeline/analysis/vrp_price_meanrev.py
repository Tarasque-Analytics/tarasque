"""
vrp_price_meanrev.py -- Does the VRP preemptively predict PRICE mean reversion?

If a stock recently DROPPED sharply AND its forward-VRP is unusually high, does
the price tend to BOUNCE over the next 21 BD? If it recently RALLIED + high VRP,
does it pull back?

Hypothesis: wide VRP = market pricing a "big move coming." If recent move has
already happened, the wide VRP may anticipate a reversal (mean reversion).
If wide VRP exists without a recent move, it may anticipate a fresh move.

Test:
  1. For each (ticker, date): trailing 21-BD return + forward 21-BD return,
     forward max-DD and forward max-rally over the 21-BD window.
  2. 3x3 grid: recent_return_tercile (DOWN/FLAT/UP) x vrp_own_pct_tercile
     (LOW/MID/HIGH). Conditional mean forward return per cell.
  3. The reversal-spread signal: (DOWN-HIGH return) - (UP-HIGH return).
     Positive = high VRP amplifies mean reversion. Compare to the same
     spread at LOW VRP -- does VRP add a directional reversal signal?
  4. HAC test on within-date long-short:
       long = (recent-DOWN + HIGH-VRP),  short = (recent-UP + HIGH-VRP)
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

REPO_ROOT = Path(__file__).resolve().parents[3]
WEBAPP_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "webapp_export" / "tickers"
OUT_DIR    = REPO_ROOT / "model" / "pipeline" / "results" / "validation"

HOLD = 21
ROLLING = 252
MIN_PERIODS = 63
HAC_LAGS = 42
START_DATE = pd.Timestamp("2015-01-01")


def trailing_pct(s: pd.Series, window: int = ROLLING,
                  min_periods: int = MIN_PERIODS) -> pd.Series:
    return s.rolling(window, min_periods=min_periods).apply(
        lambda x: (float((x[:-1] <= x[-1]).sum()) + 0.5) / len(x), raw=True)


def hac_mean(s: pd.Series, lags: int = HAC_LAGS) -> dict:
    x = s.dropna().to_numpy(float)
    if len(x) < 30:
        return {"mean": np.nan, "t": np.nan, "p": np.nan, "n": int(len(x))}
    res = sm.OLS(x, np.ones((len(x), 1))).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return {"mean": float(res.params[0]), "t": float(res.tvalues[0]),
            "p": float(res.pvalues[0]), "n": int(len(x))}


def forward_path_stats(prices: pd.Series, h: int) -> pd.DataFrame:
    """Per row: forward log-return, forward max-DD, forward max-rally over h BD."""
    n = len(prices)
    fwd_ret = np.full(n, np.nan)
    fwd_dd = np.full(n, np.nan)
    fwd_rally = np.full(n, np.nan)
    p = prices.to_numpy(float)
    for i in range(n - h):
        window = p[i:i + h + 1]
        if not (np.isfinite(window[0]) and window[0] > 0): continue
        log_path = np.log(window / window[0])
        fwd_ret[i] = log_path[-1]
        fwd_dd[i] = log_path.min()
        fwd_rally[i] = log_path.max()
    return pd.DataFrame({"fwd_ret_21": fwd_ret, "fwd_dd_21": fwd_dd,
                         "fwd_rally_21": fwd_rally}, index=prices.index)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[VRP_PRICE_MR] Loading panel + computing trailing return + forward path...")
    rows = []
    for f in sorted(WEBAPP_DIR.glob("predictions_*.csv")):
        tk = f.stem.replace("predictions_", "")
        try:
            df = pd.read_csv(f, parse_dates=["date"],
                             usecols=["date", "close", "fwd_premium_ewma_21d"])
        except Exception:
            continue
        df = df.sort_values("date").reset_index(drop=True)
        df["trail_ret_21"] = np.log(df["close"] / df["close"].shift(HOLD))
        path = forward_path_stats(df["close"], HOLD)
        df = pd.concat([df, path], axis=1)
        df["ticker"] = tk
        df["own_pct"] = trailing_pct(df["fwd_premium_ewma_21d"])
        rows.append(df)
    p = pd.concat(rows, ignore_index=True)
    p = p[p["date"] >= START_DATE].copy()
    p = p.dropna(subset=["trail_ret_21", "fwd_ret_21", "own_pct"]).copy()
    print(f"  {len(p):,} (ticker,date) rows | tickers {p['ticker'].nunique()}")

    # tercile buckets
    p["recent_dir"] = pd.qcut(p["trail_ret_21"], 3, labels=["DOWN", "FLAT", "UP"])
    p["vrp_bkt"]    = pd.qcut(p["own_pct"],     3, labels=["LOW", "MID", "HIGH"])

    # ── 1. 3x3 GRID OF FORWARD RETURN ───────────────────────────────────────
    print("\n" + "=" * 80)
    print(" 1. CONDITIONAL FORWARD RETURN GRID  (rows: recent dir | cols: VRP tercile)")
    print("=" * 80)
    grid_ret = p.groupby(["recent_dir", "vrp_bkt"], observed=True)["fwd_ret_21"].agg(["mean","count"]).unstack()
    print("  mean forward 21-BD log-return per cell:")
    print((grid_ret["mean"] * 100).round(3).to_string())
    print("\n  n per cell:")
    print(grid_ret["count"].to_string())

    print("\n  hit-rate (fwd > 0) per cell:")
    grid_hit = p.groupby(["recent_dir", "vrp_bkt"], observed=True)["fwd_ret_21"].apply(
        lambda s: float((s > 0).mean())).unstack()
    print((grid_hit * 100).round(1).to_string())

    # ── 2. REVERSAL-SPREAD SIGNAL ────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" 2. REVERSAL SPREAD: (recent-DOWN forward ret) - (recent-UP forward ret)")
    print("    per VRP tercile. Positive = VRP-conditional mean reversion exists.")
    print("=" * 80)
    rev_spreads = {}
    for vrp in ["LOW", "MID", "HIGH"]:
        down = p[(p["vrp_bkt"] == vrp) & (p["recent_dir"] == "DOWN")]["fwd_ret_21"]
        up   = p[(p["vrp_bkt"] == vrp) & (p["recent_dir"] == "UP")  ]["fwd_ret_21"]
        diff = down.mean() - up.mean()
        rev_spreads[vrp] = diff
        print(f"  VRP={vrp:4s}: DOWN mean {down.mean()*100:+.3f}%  UP mean {up.mean()*100:+.3f}%  "
              f"reversal spread = {diff*100:+.3f} pp")
    print(f"\n  >> Reversal AMPLIFICATION by VRP (HIGH vs LOW): "
          f"{(rev_spreads['HIGH'] - rev_spreads['LOW'])*100:+.3f} pp")

    # ── 3. WITHIN-DATE LONG-SHORT TEST (DOWN+HIGH long, UP+HIGH short) ──────
    print("\n" + "=" * 80)
    print(" 3. WITHIN-DATE LONG-SHORT (HAC) -- the tradeable reversal in HIGH-VRP names")
    print("    long = recent-DOWN + HIGH-VRP   short = recent-UP + HIGH-VRP")
    print("=" * 80)
    pH = p[p["vrp_bkt"] == "HIGH"].copy()
    daily = pH.groupby("date").apply(
        lambda d: (d.loc[d.recent_dir == "DOWN", "fwd_ret_21"].mean()
                 - d.loc[d.recent_dir == "UP",   "fwd_ret_21"].mean()),
        include_groups=False).dropna().rename("ls")
    h = hac_mean(daily)
    sd = daily.std()
    ann = h['mean'] * (252 / HOLD)
    ir = (h['mean'] / sd * np.sqrt(252 / HOLD)) if sd > 0 else np.nan
    print(f"  daily-spread mean: {h['mean']*100:+.4f}% per 21BD  HAC t={h['t']:+.2f}  p={h['p']:.4g}  n={h['n']}")
    print(f"  annualized LS: {ann*100:+.1f}%/yr  approx IR {ir:+.2f}  days LS>0 "
          f"{float((daily>0).mean()):.0%}")
    # Same test in LOW-VRP for control
    pL = p[p["vrp_bkt"] == "LOW"].copy()
    daily_L = pL.groupby("date").apply(
        lambda d: (d.loc[d.recent_dir == "DOWN", "fwd_ret_21"].mean()
                 - d.loc[d.recent_dir == "UP",   "fwd_ret_21"].mean()),
        include_groups=False).dropna().rename("ls")
    h_L = hac_mean(daily_L)
    print(f"\n  CONTROL (same spread but in LOW-VRP names):")
    print(f"  daily-spread mean: {h_L['mean']*100:+.4f}% per 21BD  HAC t={h_L['t']:+.2f}  p={h_L['p']:.4g}")

    # ── 4. FORWARD PATH SHAPE (max DD, max rally) per VRP bucket ─────────────
    print("\n" + "=" * 80)
    print(" 4. FORWARD 21-BD PATH SHAPE per VRP tercile -- does VRP predict wider range?")
    print("=" * 80)
    for vrp in ["LOW", "MID", "HIGH"]:
        sub = p[p["vrp_bkt"] == vrp]
        n = len(sub)
        print(f"  VRP={vrp:4s}  n={n:>7,d}  "
              f"max-DD mean {sub['fwd_dd_21'].mean()*100:+.2f}%  "
              f"max-rally mean {sub['fwd_rally_21'].mean()*100:+.2f}%  "
              f"intra-window range {(sub['fwd_rally_21']-sub['fwd_dd_21']).mean()*100:.2f}%")
    print("  (wider range at HIGH = forward path has bigger swings, consistent with the +2.6pp")
    print("   forward-vol prediction we already had — vol manifests as wider intra-window paths)")

    # ── 5. TIME STABILITY ────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" 5. TIME STABILITY 2015-2020 vs 2021-2026 on the HIGH-VRP reversal spread")
    print("=" * 80)
    for label, mask in [("2015-2020", daily.index <= pd.Timestamp("2020-12-31")),
                        ("2021-2026", daily.index >  pd.Timestamp("2020-12-31"))]:
        sub = daily[mask]
        hh = hac_mean(sub)
        print(f"  {label}: HIGH-VRP DOWN-UP reversal spread {hh['mean']*100:+.3f}% per 21BD  "
              f"(t={hh['t']:+.2f}, p={hh['p']:.3g}, n={hh['n']})")

    daily.to_csv(OUT_DIR / "vrp_price_meanrev_daily_spread.csv")
    print("\n[VRP_PRICE_MR] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

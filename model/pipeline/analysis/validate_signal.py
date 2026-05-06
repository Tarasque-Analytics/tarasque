"""
validate_signal.py — Economic-significance tests for the v10+ vol model.

Runs on the v10+ canary corpus (predictions_*.csv files). Produces:
  1. 3-sigma event lead-time precision (does the model warn before tail events)
  2. Drawdown-conditional analysis (does forecast decile predict forward drawdown)
  3. Demeaned cross-sectional IC (per-ticker drift removed; pure ranking signal)
  4. Quintile lift (top-quintile vs bottom-quintile forecast → realized vol spread)
  5. Coverage q15 backtest (does the floor signal cover what it claims)

Outputs (in model/pipeline/results/validation/):
  tail_event_precision.csv         — per-ticker event lead-time stats
  drawdown_conditional.csv         — per-(ticker × decile) forward drawdown
  cross_sectional_ic.csv           — daily IC time series
  quintile_lift.csv                — per-day quintile averages
  coverage_q15.csv                 — per-ticker realized coverage
  validation_summary.md            — one-page meeting brief
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import load_config
from ..data_loader import ParquetStore
from ..utils import DECIMAL_PRECISION, round_for_output


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS = REPO_ROOT / "model" / "pipeline" / "results"
OUT = RESULTS / "validation"
WARMUP = 252


def load_combined() -> pd.DataFrame:
    """Prefer aggregated v10+ canary csv; fall back to per-ticker files."""
    p = RESULTS / "v10_canary_combined_predictions.csv"
    if p.exists():
        df = pd.read_csv(p, parse_dates=["date"])
        return df
    frames = []
    for f in sorted(RESULTS.glob("predictions_*.csv")):
        try:
            d = pd.read_csv(f, parse_dates=["date"])
            if {"ticker", "horizon", "y_true", "y_pred"}.issubset(d.columns):
                frames.append(d)
        except Exception:
            pass
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_closes() -> pd.DataFrame:
    """Wide closes table for drawdown computations."""
    dc, _, _ = load_config()
    s = ParquetStore(dc.base_dir)
    ohlcv = s.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    ohlcv = ohlcv.drop_duplicates(subset=["date", "ticker"], keep="last")
    return ohlcv.pivot(index="date", columns="ticker", values="prc").ffill()


# ─── Test 1: 3-sigma event lead-time precision ───────────────────────────

def test_3sigma_lead(df: pd.DataFrame, lead_days: tuple = (5, 10, 21),
                    forecast_threshold_pct: float = 0.85) -> pd.DataFrame:
    """For each ticker (H=21), find 3-sigma realized-vol events and check
    whether forecast was in top quantile at T-{lead_days} before each event.

    Returns per-ticker rows with precision/recall/base-rate stats.
    """
    rows = []
    h21 = df[df["horizon"] == 21].copy()
    for tk, g in h21.groupby("ticker", observed=True):
        g = g.sort_values("date").reset_index(drop=True)
        if len(g) < WARMUP + max(lead_days):
            continue
        y = g["y_true"].values
        p = g["y_pred"].values
        # Trailing 252d rolling mean/std for 3-sigma envelope
        roll_mu = pd.Series(y).rolling(WARMUP, min_periods=WARMUP).mean().values
        roll_sd = pd.Series(y).rolling(WARMUP, min_periods=WARMUP).std().values
        is_3sig = (y > (roll_mu + 3 * roll_sd))
        # Forecast percentile (expanding window, no lookahead)
        fcst_pct = pd.Series(p).expanding(min_periods=WARMUP).rank(pct=True).values

        for lead in lead_days:
            # Lagged forecast percentile at T-lead
            shifted_pct = pd.Series(fcst_pct).shift(lead).values
            valid = ~np.isnan(shifted_pct) & ~np.isnan(roll_mu)
            if valid.sum() < 100:
                continue

            elevated = shifted_pct > forecast_threshold_pct
            event = is_3sig

            # Confusion matrix on valid mask
            v = valid
            n = int(v.sum())
            tp = int((elevated[v] & event[v]).sum())
            fp = int((elevated[v] & ~event[v]).sum())
            fn = int((~elevated[v] & event[v]).sum())
            tn = int((~elevated[v] & ~event[v]).sum())

            base_rate = (event[v]).mean()
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            lift = precision / base_rate if base_rate > 0 else 0.0

            rows.append({
                "ticker": tk,
                "lead_days": lead,
                "n_obs": n,
                "n_3sigma_events": int(event[v].sum()),
                "base_rate_event": float(base_rate),
                "precision_at_top15pct_forecast": float(precision),
                "recall": float(recall),
                "lift_vs_base_rate": float(lift),
            })
    return pd.DataFrame(rows)


# ─── Test 2: Drawdown-conditional ─────────────────────────────────────────

def test_drawdown_conditional(df: pd.DataFrame, closes: pd.DataFrame,
                               horizons: tuple = (21, 63, 126)) -> pd.DataFrame:
    """For each (ticker, horizon, forecast decile), compute mean and worst-decile
    forward drawdown of close price.
    """
    rows = []
    for h in horizons:
        sub = df[df["horizon"] == h].copy()
        for tk, g in sub.groupby("ticker", observed=True):
            if tk not in closes.columns:
                continue
            g = g.sort_values("date").reset_index(drop=True)
            tk_closes = closes[tk].reindex(g["date"]).values
            # forward drawdown over h days
            n = len(g)
            fwd_dd = np.full(n, np.nan)
            for i in range(n - h):
                window = tk_closes[i + 1: i + h + 1]
                if np.isnan(window).all() or np.isnan(tk_closes[i]):
                    continue
                fwd_dd[i] = float(np.nanmin(window) / tk_closes[i] - 1.0)

            # Forecast decile (expanding-window CDF rank)
            pct = pd.Series(g["y_pred"]).expanding(min_periods=WARMUP).rank(pct=True).values
            valid = ~np.isnan(pct) & ~np.isnan(fwd_dd)
            if valid.sum() < 200:
                continue
            decile = np.floor(pct * 10).clip(0, 9).astype(int)
            for d in range(10):
                m = valid & (decile == d)
                if m.sum() < 20:
                    continue
                rows.append({
                    "ticker": tk,
                    "horizon": h,
                    "decile": d,
                    "n": int(m.sum()),
                    "mean_fwd_dd": float(np.nanmean(fwd_dd[m])),
                    "median_fwd_dd": float(np.nanmedian(fwd_dd[m])),
                    "p10_fwd_dd": float(np.nanpercentile(fwd_dd[m], 10)),
                })
    return pd.DataFrame(rows)


# ─── Test 3 + 4: Demeaned cross-sectional IC + quintile lift ─────────────

def test_cross_sectional_ic_residual(df: pd.DataFrame, horizon: int = 21) -> pd.DataFrame:
    """Cross-sectional IC on TICKER-SPECIFIC residuals.

    The previous test_cross_sectional_ic was inflated because all tickers move
    together in vol regimes — high cross-sectional rank correlation when "market
    vol is high everyone's at top quartile." That measures regime detection, not
    stock-picking.

    This test partials out the cross-sectional mean per date:
      pred_resid_i,t = pred_self_pct_i,t - mean(pred_self_pct_*,t)
      true_resid_i,t = true_self_pct_i,t - mean(true_self_pct_*,t)
    Then computes daily Spearman of pred_resid vs true_resid.

    This isolates "which stock is HIGHER vol than its peers RIGHT NOW" signal,
    which is the actual cross-sectional alpha question.
    """
    # Correct approach: work in raw vol space, NOT ranks. Subtract per-ticker
    # rolling mean (removes ticker level), then subtract cross-sectional mean
    # per date (removes market-wide regime). Rank the residuals cross-sectionally.
    sub = df[df["horizon"] == horizon].copy()
    sub = sub.sort_values(["ticker", "date"]).reset_index(drop=True)
    # Per-ticker rolling 252d mean (no lookahead) — removes ticker-specific level
    sub["pred_self_dm"] = (sub.groupby("ticker", observed=True)["y_pred"]
                              .transform(lambda s: s - s.rolling(WARMUP, min_periods=WARMUP).mean()))
    sub["true_self_dm"] = (sub.groupby("ticker", observed=True)["y_true"]
                              .transform(lambda s: s - s.rolling(WARMUP, min_periods=WARMUP).mean()))
    sub = sub.dropna(subset=["pred_self_dm", "true_self_dm"])

    # Cross-sectional demean per date — removes market-wide regime component
    sub["pred_resid"] = sub.groupby("date", observed=True)["pred_self_dm"].transform(
        lambda s: s - s.mean())
    sub["true_resid"] = sub.groupby("date", observed=True)["true_self_dm"].transform(
        lambda s: s - s.mean())

    ic_rows = []
    for d, g in sub.groupby("date", observed=True):
        if len(g) < 5:
            continue
        x = g["pred_resid"].rank()
        y = g["true_resid"].rank()
        if x.std() == 0 or y.std() == 0:
            continue
        ic = float(np.corrcoef(x, y)[0, 1])
        ic_rows.append({"date": d, "n_tickers": len(g), "ic_residual": ic})
    return pd.DataFrame(ic_rows)


def test_cross_sectional_ic(df: pd.DataFrame, horizon: int = 21) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-date cross-sectional Spearman IC + quintile lift.

    Demeaning approach: rank each ticker's forecast within its own
    expanding-window history (no lookahead) → cross-rank across tickers per date.

    Returns (ic_daily, quintile_daily).
    """
    sub = df[df["horizon"] == horizon].copy()
    sub = sub.sort_values(["ticker", "date"]).reset_index(drop=True)
    # Ticker-level expanding rank (no lookahead)
    sub["pred_pct_self"] = (sub.groupby("ticker", observed=True)["y_pred"]
                              .transform(lambda s: s.expanding(min_periods=WARMUP).rank(pct=True)))
    sub["true_pct_self"] = (sub.groupby("ticker", observed=True)["y_true"]
                              .transform(lambda s: s.expanding(min_periods=WARMUP).rank(pct=True)))
    sub = sub.dropna(subset=["pred_pct_self", "true_pct_self"])
    # Per-date cross-sectional Spearman (use the demeaned percentiles)
    ic_rows = []
    quint_rows = []
    for d, g in sub.groupby("date", observed=True):
        if len(g) < 5:
            continue
        # Spearman = Pearson on ranks; rank() does the right thing
        x = g["pred_pct_self"].rank()
        y = g["true_pct_self"].rank()
        if x.std() == 0 or y.std() == 0:
            continue
        ic = float(np.corrcoef(x, y)[0, 1])
        ic_rows.append({"date": d, "n_tickers": len(g), "ic": ic})

        # Quintile lift on raw realized vol
        g = g.copy()
        g["fcst_quintile"] = pd.qcut(g["pred_pct_self"], q=5, labels=False,
                                       duplicates="drop")
        for q in range(5):
            qsub = g[g["fcst_quintile"] == q]
            if len(qsub) > 0:
                quint_rows.append({
                    "date": d, "quintile": q, "n": len(qsub),
                    "mean_y_true": float(qsub["y_true"].mean()),
                })
    return pd.DataFrame(ic_rows), pd.DataFrame(quint_rows)


# ─── Test 5: Coverage q15 ────────────────────────────────────────────────

def test_coverage_q15(df: pd.DataFrame) -> pd.DataFrame:
    """For each (ticker, horizon), realized coverage of the q15 floor.

    Definition: P(y_true > y_pred_q15). Target: 0.85.
    """
    if "y_pred_q15" not in df.columns:
        return pd.DataFrame()
    rows = []
    for (tk, h), g in df.groupby(["ticker", "horizon"], observed=True):
        g = g.dropna(subset=["y_true", "y_pred_q15"])
        if len(g) < 100:
            continue
        cov = float((g["y_true"] > g["y_pred_q15"]).mean())
        rows.append({
            "ticker": tk, "horizon": int(h),
            "coverage_q15": cov,
            "delta_from_target": cov - 0.85,
            "n": int(len(g)),
        })
    return pd.DataFrame(rows)


# ─── Summary writer ───────────────────────────────────────────────────────

def write_summary(t1: pd.DataFrame, t2: pd.DataFrame,
                  ic: pd.DataFrame, quintile: pd.DataFrame,
                  cov: pd.DataFrame, out_path: Path) -> None:
    lines = ["# v10+ Signal Validation — Economic Significance Brief", "",
             f"_Generated {pd.Timestamp.now().strftime('%Y-%m-%d')}._", ""]

    # Tail event lead-time
    lines.append("## 1. 3-sigma event lead-time precision")
    if not t1.empty:
        for lead in sorted(t1["lead_days"].unique()):
            sub = t1[t1["lead_days"] == lead]
            mean_lift = sub["lift_vs_base_rate"].replace([np.inf, -np.inf], np.nan).mean()
            mean_recall = sub["recall"].mean()
            mean_prec = sub["precision_at_top15pct_forecast"].mean()
            mean_base = sub["base_rate_event"].mean()
            lines.append(
                f"- **Lead {lead}d**: n={len(sub)} tickers, "
                f"base rate={mean_base:.3%}, precision (top-15% forecast)="
                f"**{mean_prec:.3%}**, recall={mean_recall:.3%}, "
                f"lift={mean_lift:.2f}x"
            )
    lines.append("")

    # Drawdown-conditional
    lines.append("## 2. Drawdown-conditional (forecast decile -> forward DD)")
    if not t2.empty:
        for h in sorted(t2["horizon"].unique()):
            sub = t2[t2["horizon"] == h]
            top = sub[sub["decile"] == 9]["mean_fwd_dd"].mean()
            bot = sub[sub["decile"] == 0]["mean_fwd_dd"].mean()
            lines.append(f"- **H={int(h)}d**: top-decile mean DD={top:.3%}, "
                         f"bottom-decile DD={bot:.3%}, spread={top - bot:.3%}")
    lines.append("")

    # Cross-sectional IC
    lines.append("## 3. Demeaned cross-sectional IC")
    if not ic.empty:
        lines.append(f"- Daily IC mean: **{ic['ic'].mean():.4f}**, "
                     f"std: {ic['ic'].std():.4f}, n_dates: {len(ic)}")
        lines.append(f"- IC > 0 fraction: {(ic['ic'] > 0).mean():.2%}")
        lines.append(f"- IC > 0.05 fraction: {(ic['ic'] > 0.05).mean():.2%}")
        lines.append(f"- t-stat (IC mean vs zero): "
                     f"{ic['ic'].mean() / (ic['ic'].std() / np.sqrt(len(ic))):.2f}")
    lines.append("")

    # Quintile lift
    lines.append("## 4. Quintile lift (cross-sectional)")
    if not quintile.empty:
        agg = quintile.groupby("quintile")["mean_y_true"].mean()
        lines.append("Mean realized vol by forecast quintile (cross-sectional, all dates):")
        for q, v in agg.items():
            lines.append(f"- Q{int(q)}: {v:.4f}")
        lift = agg.iloc[-1] / agg.iloc[0] if agg.iloc[0] > 0 else float('nan')
        lines.append(f"- **Q5/Q1 lift: {lift:.2f}x**")
    lines.append("")

    # Coverage q15
    lines.append("## 5. Coverage q15 (floor signal validation)")
    if not cov.empty:
        for h in sorted(cov["horizon"].unique()):
            sub = cov[cov["horizon"] == h]
            mean_cov = sub["coverage_q15"].mean()
            in_band = ((sub["coverage_q15"] >= 0.80) & (sub["coverage_q15"] <= 0.90)).sum()
            lines.append(f"- **H={int(h)}**: mean coverage={mean_cov:.3f} "
                         f"(target 0.85), in [0.80, 0.90]: {in_band}/{len(sub)}")
    lines.append("")
    lines.append("## Caveats")
    lines.append("- All tests are in-sample (walk-forward but no held-out test set).")
    lines.append("- Survivorship bias: tickers in our 91-name corpus all survived 2014-2025.")
    lines.append("- Period sensitivity: 2020-2021 vol regime dominates the realized vol distribution.")
    lines.append("- DM test vs HAR-RV: see prior `benchmark_comparison.csv` (v6 audit, 97/97 tickers beat persistence).")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = load_combined()
    if df.empty:
        print("[VALIDATE] No predictions found. Abort.")
        return
    print(f"[VALIDATE] Loaded {len(df):,} rows, {df['ticker'].nunique()} tickers.")

    closes = load_closes()

    print("[VALIDATE] Test 1: 3-sigma event lead-time...")
    t1 = test_3sigma_lead(df)
    if not t1.empty:
        round_for_output(t1, DECIMAL_PRECISION).to_csv(OUT / "tail_event_precision.csv", index=False)
        print(f"  wrote tail_event_precision.csv ({len(t1)} rows)")

    print("[VALIDATE] Test 2: drawdown-conditional...")
    t2 = test_drawdown_conditional(df, closes)
    if not t2.empty:
        round_for_output(t2, DECIMAL_PRECISION).to_csv(OUT / "drawdown_conditional.csv", index=False)
        print(f"  wrote drawdown_conditional.csv ({len(t2)} rows)")

    print("[VALIDATE] Test 3+4: cross-sectional IC + quintile lift...")
    ic, quintile = test_cross_sectional_ic(df)
    if not ic.empty:
        round_for_output(ic, DECIMAL_PRECISION).to_csv(OUT / "cross_sectional_ic.csv", index=False)
        round_for_output(quintile, DECIMAL_PRECISION).to_csv(OUT / "quintile_lift.csv", index=False)
        print(f"  wrote cross_sectional_ic.csv ({len(ic)} dates), "
              f"quintile_lift.csv ({len(quintile)} rows)")

    print("[VALIDATE] Test 3b: cross-sectional IC RESIDUAL (regime-removed)...")
    ic_resid = test_cross_sectional_ic_residual(df)
    if not ic_resid.empty:
        round_for_output(ic_resid, DECIMAL_PRECISION).to_csv(OUT / "cross_sectional_ic_residual.csv", index=False)
        print(f"  wrote cross_sectional_ic_residual.csv ({len(ic_resid)} dates)")
        # Print quick comparison
        ic_full = ic["ic"].mean() if not ic.empty else float('nan')
        ic_res = ic_resid["ic_residual"].mean()
        print(f"  Mean IC (regime+stock): {ic_full:.4f}")
        print(f"  Mean IC (stock only, regime-removed): {ic_res:.4f}")
        print(f"  Regime component: {ic_full - ic_res:.4f}")

    print("[VALIDATE] Test 5: coverage q15...")
    cov = test_coverage_q15(df)
    if not cov.empty:
        round_for_output(cov, DECIMAL_PRECISION).to_csv(OUT / "coverage_q15.csv", index=False)
        print(f"  wrote coverage_q15.csv ({len(cov)} rows)")

    write_summary(t1, t2, ic, quintile, cov, OUT / "validation_summary.md")
    print(f"  wrote validation_summary.md")


if __name__ == "__main__":
    main()

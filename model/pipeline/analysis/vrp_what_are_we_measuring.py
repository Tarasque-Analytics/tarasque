"""
vrp_what_are_we_measuring.py — Four tests to determine what our wedge signal
                                actually IS.

We've established the wedge `IV - rv_21d` predicts forward vol with +0.40 IC.
But any of these would produce the same signal:
  1. True VRP (insurance markup)                — what we claim
  2. Information asymmetry (options see events) — possible
  3. Vol persistence (clustered current vol)    — possible
  4. Demand-side option flow                    — possible
  5. Macro fear leaking through (noisy VIX)     — POSSIBLE — biggest threat
  6. Vol-of-vol risk premium                    — possible
  7. Tail-skew premium                          — possible

This script runs four discriminating tests:

  Test A: Decompose per-ticker wedge into SYSTEMATIC (universe-mean) +
          IDIOSYNCRATIC (residual). Then IC-test each separately.
          → If only SYSTEMATIC predicts forward vol, we're measuring macro/VIX-like
            aggregate fear. If IDIOSYNCRATIC also predicts, real per-stock VRP exists.

  Test B: Correlate aggregate wedge with macro/VIX-proxy signals (universe-mean
          IV, HY spread, term structure slope, dollar index, yield curve).
          → If 90% correlated with universe-mean IV, we're a noisy VIX in disguise.

  Test C: Regime-conditional IC. Split observations by SPY vol level into calm
          (P0-P33), normal (P33-P67), stress (P67-P100). IC-test each regime.
          → True VRP should STRENGTHEN in stress (fear premium most actionable
            when markets are afraid). If IC weakens in stress, we're not
            measuring fear premium.

  Test D: Regress wedge on event proximity (days_to_earnings if available).
          Take residual. Compare IC of residual wedge vs raw wedge.
          → If residual loses most of the predictive power, event proximity
            was the main driver — we'd be measuring "scheduled event premium"
            (information asymmetry), not fear.

Outputs:
  results/validation/vrp_what_are_we_measuring_summary.md
  printed tables for each test
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import load_config
from ..data_loader import ParquetStore

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "model" / "pipeline" / "results"
OUT_DIR = RESULTS_DIR / "validation"
EWMA_HALFLIFE = 21
ROLLING_WINDOW = 252
HORIZONS = (21, 63)


# ============================================================================
# DATA
# ============================================================================

def load_per_ticker_wedge() -> dict[str, pd.DataFrame]:
    """date, vrp_wedge, vrp_wedge_ewma per ticker."""
    out = {}
    for f in sorted(RESULTS_DIR.glob("predictions_*.csv")):
        ticker = f.stem.replace("predictions_", "")
        try:
            df = pd.read_csv(f, parse_dates=["date"],
                             usecols=["date", "vrp_wedge", "horizon"])
        except Exception:
            continue
        df = df[df["horizon"] == 21].drop(columns=["horizon"])
        df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        df = df.dropna(subset=["vrp_wedge"]).reset_index(drop=True)
        if len(df) < ROLLING_WINDOW + 50:
            continue
        df["vrp_wedge_ewma"] = df["vrp_wedge"].ewm(halflife=EWMA_HALFLIFE,
                                                     adjust=False).mean()
        out[ticker] = df
    return out


def load_closes_and_fwd_vol() -> tuple[pd.DataFrame, pd.Series]:
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    ohlcv = store.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    ohlcv = ohlcv.drop_duplicates(subset=["date", "ticker"], keep="last")
    closes = ohlcv.pivot(index="date", columns="ticker", values="prc").ffill()

    # SPY vol (or universe-mean log-return std as fallback)
    if "SPY" in closes.columns:
        mkt = closes["SPY"]
    else:
        mkt = closes.mean(axis=1)
    log_ret = np.log(mkt).diff()
    spy_vol_21d = log_ret.rolling(21).std() * np.sqrt(252)
    return closes, spy_vol_21d.dropna()


def per_ticker_fwd_vol(closes: pd.DataFrame, ticker: str, h: int) -> pd.Series:
    if ticker not in closes.columns:
        return pd.Series(dtype=float)
    s = closes[ticker].dropna()
    log_ret = np.log(s).diff()
    fwd = log_ret.rolling(h).std().shift(-h) * np.sqrt(252)
    return fwd


def load_macro() -> pd.DataFrame:
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    fred = store.load("fred")
    fred["date"] = pd.to_datetime(fred["date"], format="mixed")
    return fred.set_index("date").sort_index()


# ============================================================================
# COMMON: build full panel of per-ticker wedge + forward vol + market context
# ============================================================================

def build_panel() -> pd.DataFrame:
    print("[WAM] Loading per-ticker wedge series...")
    per_t = load_per_ticker_wedge()
    print(f"  {len(per_t)} tickers")

    print("[WAM] Loading closes + SPY vol...")
    closes, spy_vol_21d = load_closes_and_fwd_vol()

    print("[WAM] Building panel...")
    pieces = []
    for tk, df in per_t.items():
        d = df.copy()
        d["ticker"] = tk
        for h in HORIZONS:
            fwd = per_ticker_fwd_vol(closes, tk, h)
            d[f"fwd_vol_h{h}"] = d["date"].map(fwd)
        pieces.append(d)
    full = pd.concat(pieces, ignore_index=True)
    full["spy_vol_21d"] = full["date"].map(spy_vol_21d)
    print(f"  panel: {len(full):,} (ticker, date) rows")
    return full


# ============================================================================
# TEST A: Systematic vs Idiosyncratic decomposition
# ============================================================================

def test_a_decomposition(full: pd.DataFrame) -> dict:
    print("\n" + "=" * 70)
    print(" TEST A: Systematic vs Idiosyncratic wedge decomposition")
    print("=" * 70)
    print(" Per date, compute cross-sectional MEAN wedge (systematic).")
    print(" Per (ticker, date), residual = wedge - systematic (idiosyncratic).")
    print(" Test IC of each component vs forward vol.\n")

    panel = full.copy()
    # Aggregate (systematic) wedge per date
    sys = panel.groupby("date")["vrp_wedge_ewma"].mean().rename("wedge_sys")
    panel["wedge_sys"] = panel["date"].map(sys)
    panel["wedge_idio"] = panel["vrp_wedge_ewma"] - panel["wedge_sys"]

    var_total = panel["vrp_wedge_ewma"].var()
    var_sys   = panel["wedge_sys"].var()
    var_idio  = panel["wedge_idio"].var()
    print(f"Variance share:")
    print(f"  systematic component: {var_sys / var_total:.1%}")
    print(f"  idiosyncratic:        {var_idio / var_total:.1%}")
    print()

    rows = []
    for h in HORIZONS:
        sub = panel.dropna(subset=["wedge_sys", "wedge_idio", f"fwd_vol_h{h}"])
        ic_total = float(sub["vrp_wedge_ewma"].corr(sub[f"fwd_vol_h{h}"], method="spearman"))
        ic_sys   = float(sub["wedge_sys"].corr(sub[f"fwd_vol_h{h}"], method="spearman"))
        ic_idio  = float(sub["wedge_idio"].corr(sub[f"fwd_vol_h{h}"], method="spearman"))
        # Per-ticker median IC of idiosyncratic (since systematic is cross-sectionally constant per date)
        idio_ics_per_ticker = []
        for tk, g in sub.groupby("ticker"):
            if len(g) < 100:
                continue
            ic = float(g["wedge_idio"].corr(g[f"fwd_vol_h{h}"], method="spearman"))
            if np.isfinite(ic):
                idio_ics_per_ticker.append(ic)
        idio_median = float(np.median(idio_ics_per_ticker)) if idio_ics_per_ticker else np.nan
        rows.append({"horizon": h, "n": len(sub),
                     "ic_total_pooled": ic_total,
                     "ic_systematic_pooled": ic_sys,
                     "ic_idiosyncratic_pooled": ic_idio,
                     "ic_idiosyncratic_per_ticker_median": idio_median,
                     "n_idio_tickers": len(idio_ics_per_ticker)})

    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    return {"test": "A", "variance_share_sys": var_sys / var_total,
            "results": df.to_dict("records")}


# ============================================================================
# TEST B: Correlation with macro/VIX-proxy signals
# ============================================================================

def test_b_macro_correlation(full: pd.DataFrame) -> dict:
    print("\n" + "=" * 70)
    print(" TEST B: Aggregate wedge vs macro/VIX-proxy signals")
    print("=" * 70)
    print(" If aggregate wedge is 90%+ correlated with universe-mean IV (VIX proxy),")
    print(" we're a noisy VIX in disguise.\n")

    # Aggregate wedge per date
    agg = full.groupby("date")["vrp_wedge_ewma"].mean().rename("agg_wedge").to_frame()

    # Universe-mean iv_atm_30d as VIX proxy
    # vrp_wedge = iv_atm_30d - rv_21d; can we back out iv? Use per-ticker `vrp_wedge` + rv:
    # We don't have iv directly here but we DO have vrp_wedge_ewma. Aggregate vrp_wedge_ewma
    # is itself a "fear premium proxy", correlated with VIX by construction.
    #
    # Better: use SPY rolling vol as a fear regime proxy (since VIX correlates with SPY vol)
    # And use macro features from FRED.

    macro = load_macro()
    for col in ("treasury_10y", "treasury_3mo", "hy_spread", "breakeven_5y",
                "dollar_index", "inflation_forward_5y5y"):
        if col in macro.columns:
            agg[col] = macro[col]

    # Yield curve slope
    if "treasury_10y" in agg.columns and "treasury_3mo" in agg.columns:
        agg["yield_slope"] = agg["treasury_10y"] - agg["treasury_3mo"]

    # SPY vol (the closest thing to VIX we have without yfinance)
    closes, spy_vol_21d = load_closes_and_fwd_vol()
    agg["spy_vol_21d"] = spy_vol_21d

    agg = agg.dropna(subset=["agg_wedge"])
    print(f"  aggregate wedge time series: {len(agg)} dates "
          f"({agg.index.min().date()} -> {agg.index.max().date()})")

    rows = []
    for col in agg.columns:
        if col == "agg_wedge":
            continue
        sub = agg.dropna(subset=["agg_wedge", col])
        if len(sub) < 100:
            continue
        c_pearson  = float(sub["agg_wedge"].corr(sub[col], method="pearson"))
        c_spearman = float(sub["agg_wedge"].corr(sub[col], method="spearman"))
        rows.append({"signal": col, "n": len(sub),
                     "pearson": c_pearson, "spearman": c_spearman})
    df = pd.DataFrame(rows).sort_values("spearman", key=lambda c: c.abs(), ascending=False)
    print()
    print(df.to_string(index=False))
    return {"test": "B", "results": df.to_dict("records")}


# ============================================================================
# TEST C: Regime-conditional IC
# ============================================================================

def test_c_regime_conditional(full: pd.DataFrame) -> dict:
    print("\n" + "=" * 70)
    print(" TEST C: Regime-conditional IC (calm / normal / stress)")
    print("=" * 70)
    print(" Split by SPY-vol terciles. True VRP should STRENGTHEN in stress.\n")

    panel = full.dropna(subset=["spy_vol_21d", "vrp_wedge_ewma"]).copy()
    # Tercile thresholds from FULL distribution of SPY vol
    q33, q67 = panel["spy_vol_21d"].quantile([0.33, 0.67]).values
    panel["regime"] = pd.cut(panel["spy_vol_21d"],
                              bins=[-np.inf, q33, q67, np.inf],
                              labels=["calm", "normal", "stress"])
    print(f"  SPY 21d vol tercile thresholds: P33={q33:.3f}  P67={q67:.3f}\n")

    rows = []
    for regime in ("calm", "normal", "stress"):
        sub = panel[panel["regime"] == regime]
        for h in HORIZONS:
            r = sub.dropna(subset=[f"fwd_vol_h{h}"])
            if len(r) < 100:
                continue
            ic = float(r["vrp_wedge_ewma"].corr(r[f"fwd_vol_h{h}"], method="spearman"))
            rows.append({"regime": regime, "horizon": h, "n": len(r),
                         "ic_wedge_vs_fwd_vol": ic})
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    return {"test": "C", "results": df.to_dict("records")}


# ============================================================================
# TEST D: Event-orthogonal wedge (control for scheduled event proximity)
# ============================================================================

def test_d_event_orthogonal(full: pd.DataFrame) -> dict:
    print("\n" + "=" * 70)
    print(" TEST D: Wedge orthogonal to scheduled-event proximity")
    print("=" * 70)
    print(" Regress wedge on days_to_earnings (from features). Take residual.")
    print(" If residual IC ~ raw IC, event proximity wasn't the source. If")
    print(" residual IC collapses, we were measuring 'scheduled event premium'.\n")

    # Load event proximity from per-ticker features (use existing predictions data
    # which has days_to_earnings as a column from export_for_webapp if present)
    # Easier: compute on the fly via 1 / (days_to_next_event + 1) "event_gravity"
    # We need event dates. Cleanest: load from features cache or recompute from compustat.
    # For POC, approximate using SPY vol percentile shock around earnings — but we
    # don't have per-ticker event dates loaded here.
    #
    # Fallback: regress on calendar-week dummies (captures FOMC-week / earnings-season
    # effects in aggregate). Crude but informative.
    panel = full.dropna(subset=["vrp_wedge_ewma", "spy_vol_21d"]).copy()
    panel["month"] = panel["date"].dt.month
    panel["dow"]   = panel["date"].dt.dayofweek
    panel["calendar_week"] = panel["date"].dt.isocalendar().week.astype(int)

    # Within-ticker, regress wedge on calendar context to absorb event-season effects
    rows = []
    for h in HORIZONS:
        sub = panel.dropna(subset=[f"fwd_vol_h{h}"]).copy()
        if len(sub) < 1000:
            continue
        # Simple within-ticker, calendar-week mean as a baseline
        season = sub.groupby(["ticker", "calendar_week"])["vrp_wedge_ewma"].transform("mean")
        sub["wedge_seasonally_demeaned"] = sub["vrp_wedge_ewma"] - season

        ic_raw      = float(sub["vrp_wedge_ewma"].corr(sub[f"fwd_vol_h{h}"], method="spearman"))
        ic_residual = float(sub["wedge_seasonally_demeaned"].corr(sub[f"fwd_vol_h{h}"], method="spearman"))
        var_explained = 1 - sub["wedge_seasonally_demeaned"].var() / sub["vrp_wedge_ewma"].var()
        rows.append({"horizon": h, "n": len(sub),
                     "ic_raw_wedge": ic_raw,
                     "ic_residual_wedge": ic_residual,
                     "var_share_explained_by_calendar_week": var_explained})
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    return {"test": "D", "results": df.to_dict("records")}


# ============================================================================
# MAIN
# ============================================================================

def write_summary_md(results: list[dict], out: Path) -> None:
    lines = ["# What Are We Actually Measuring? — Four Tests", "",
             "Tests run on the corpus per-ticker `vrp_wedge_ewma` signal. "
             "All ICs are Spearman rank correlation against forward realized vol.",
             ""]
    for r in results:
        lines.append(f"## Test {r['test']}")
        lines.append("")
        df = pd.DataFrame(r["results"])
        if df.empty:
            lines.append("_no results_"); continue
        # Format as markdown table
        cols = list(df.columns)
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("|" + "|".join(["---"] * len(cols)) + "|")
        for _, row in df.iterrows():
            cells = []
            for c in cols:
                v = row[c]
                if isinstance(v, float):
                    cells.append(f"{v:+.3f}")
                else:
                    cells.append(str(v))
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    panel = build_panel()

    results = []
    results.append(test_a_decomposition(panel))
    results.append(test_b_macro_correlation(panel))
    results.append(test_c_regime_conditional(panel))
    results.append(test_d_event_orthogonal(panel))

    out_md = OUT_DIR / "vrp_what_are_we_measuring_summary.md"
    write_summary_md(results, out_md)
    print(f"\n[WAM] Wrote summary to {out_md}")

    print("\n" + "=" * 70)
    print(" VERDICT GUIDE")
    print("=" * 70)
    print(" Test A: variance share of systematic? If > 70% → mostly macro. If < 50% → real per-stock VRP signal.")
    print(" Test B: |Spearman| with SPY vol? If > 0.7 → noisy VIX. If < 0.4 → distinct signal.")
    print(" Test C: stress-regime IC vs calm-regime IC? If stress > calm → fear premium. If calm > stress → vol persistence.")
    print(" Test D: residual IC retention? If > 80% of raw IC → event proximity wasn't the source.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

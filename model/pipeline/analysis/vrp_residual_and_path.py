"""
vrp_residual_and_path.py — Two follow-on tests:

  Test E: Strip BOTH calendar-week-mean (per ticker) AND cross-sectional mean
          (per date) from the wedge. Is there ANY predictive power left in the
          "doubly-residualized" wedge? If yes → there IS a per-stock fear-premium
          signal hiding inside, just smaller than the headline +0.40 IC.

  Test F: Different goalpost — use FORWARD ABSOLUTE PATH LENGTH instead of
          std-based realized vol as the dependent variable.
            fwd_path_h = sum(|log_return_t|) over next h BD
          This is what GAMMA EXPOSURE cares about: how much did the stock
          actually MOVE (regardless of direction), not how dispersed were
          its log returns. A different but defensible target than fwd_vol.

Tests run on the same 267k-obs panel as `vrp_what_are_we_measuring.py`.

Outputs:
  results/validation/vrp_residual_path.csv
  printed comparison tables
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


def load_per_ticker_wedge() -> dict[str, pd.DataFrame]:
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


def load_closes() -> pd.DataFrame:
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    ohlcv = store.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    ohlcv = ohlcv.drop_duplicates(subset=["date", "ticker"], keep="last")
    return ohlcv.pivot(index="date", columns="ticker", values="prc").ffill()


def per_ticker_fwd_vol(closes: pd.DataFrame, ticker: str, h: int) -> pd.Series:
    """Forward annualized realized vol via log-return std."""
    if ticker not in closes.columns:
        return pd.Series(dtype=float)
    s = closes[ticker].dropna()
    log_ret = np.log(s).diff()
    return log_ret.rolling(h).std().shift(-h) * np.sqrt(252)


def per_ticker_fwd_path(closes: pd.DataFrame, ticker: str, h: int) -> pd.Series:
    """Forward absolute path length: sum of |log_return| over next h BD.
    Measures total absolute movement regardless of direction."""
    if ticker not in closes.columns:
        return pd.Series(dtype=float)
    s = closes[ticker].dropna()
    log_ret = np.log(s).diff().abs()
    return log_ret.rolling(h).sum().shift(-h)


def build_panel() -> pd.DataFrame:
    print("[E_F] Loading per-ticker wedge series...")
    per_t = load_per_ticker_wedge()
    print(f"  {len(per_t)} tickers")

    print("[E_F] Loading closes...")
    closes = load_closes()

    print("[E_F] Building panel (vol + path-length targets)...")
    pieces = []
    for tk, df in per_t.items():
        d = df.copy()
        d["ticker"] = tk
        for h in HORIZONS:
            d[f"fwd_vol_h{h}"]  = d["date"].map(per_ticker_fwd_vol(closes, tk, h))
            d[f"fwd_path_h{h}"] = d["date"].map(per_ticker_fwd_path(closes, tk, h))
        pieces.append(d)
    full = pd.concat(pieces, ignore_index=True)
    print(f"  panel: {len(full):,} (ticker, date) rows")
    return full


def add_residualized_wedge(panel: pd.DataFrame) -> pd.DataFrame:
    """Doubly-residualized wedge:
       wedge_residual = wedge − (per-ticker calendar-week mean) − (per-date cross-section mean)"""
    df = panel.copy()
    df["calendar_week"] = df["date"].dt.isocalendar().week.astype(int)

    # Per-ticker × calendar-week mean (Test D component — earnings season pattern)
    df["ticker_week_mean"] = df.groupby(["ticker", "calendar_week"])["vrp_wedge_ewma"].transform("mean")

    # Per-date cross-section mean (systematic / macro component from Test A)
    df["xs_date_mean"] = df.groupby("date")["vrp_wedge_ewma"].transform("mean")

    # Doubly residualized
    df["wedge_minus_week"] = df["vrp_wedge_ewma"] - df["ticker_week_mean"]
    df["wedge_minus_both"] = df["vrp_wedge_ewma"] - df["ticker_week_mean"] - df["xs_date_mean"]
    return df


def ic_table(df: pd.DataFrame, predictors: list, targets: list) -> pd.DataFrame:
    rows = []
    for pred in predictors:
        for tgt in targets:
            sub = df.dropna(subset=[pred, tgt])
            if len(sub) < 1000:
                continue
            ic_pool = float(sub[pred].corr(sub[tgt], method="spearman"))
            # Per-ticker median
            per_t = []
            for tk, g in sub.groupby("ticker"):
                if len(g) < 100:
                    continue
                ic = float(g[pred].corr(g[tgt], method="spearman"))
                if np.isfinite(ic):
                    per_t.append(ic)
            ic_med = float(np.median(per_t)) if per_t else np.nan
            rows.append({"predictor": pred, "target": tgt,
                         "n_obs": len(sub),
                         "ic_pooled": ic_pool,
                         "ic_per_ticker_median": ic_med,
                         "n_tickers": len(per_t)})
    return pd.DataFrame(rows)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    panel = build_panel()
    panel = add_residualized_wedge(panel)

    # === TEST E ===
    print("\n" + "=" * 70)
    print(" TEST E: residual wedge after stripping seasonality + macro/systematic")
    print("=" * 70)
    print(" Original wedge → strip calendar-week-mean (per ticker) → strip cross-sectional date mean")
    print(" Is there ANY signal left? If yes → real per-stock VRP residual exists.\n")

    predictors_e = ["vrp_wedge_ewma", "wedge_minus_week", "wedge_minus_both"]
    targets_e = [f"fwd_vol_h{h}" for h in HORIZONS]
    table_e = ic_table(panel, predictors_e, targets_e)
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(table_e.to_string(index=False))

    # Variance attribution
    total_var = panel["vrp_wedge_ewma"].var()
    week_var  = panel["ticker_week_mean"].var()
    xs_var    = panel["xs_date_mean"].var()
    week_only_residual_var = panel["wedge_minus_week"].var()
    both_residual_var = panel["wedge_minus_both"].var()
    print(f"\nVariance attribution of wedge_ewma (corpus):")
    print(f"  total var                    = {total_var:.6f}")
    print(f"  share explained by week-mean = {1 - week_only_residual_var/total_var:.1%}")
    print(f"  share explained by both      = {1 - both_residual_var/total_var:.1%}")

    # === TEST F ===
    print("\n" + "=" * 70)
    print(" TEST F: alternative goalpost — forward ABSOLUTE PATH LENGTH")
    print("=" * 70)
    print(" fwd_path_h = sum(|log_return|) over next h BD. Measures total movement")
    print(" magnitude regardless of direction. What gamma exposure actually cares about.\n")

    predictors_f = ["vrp_wedge_ewma", "wedge_minus_week", "wedge_minus_both"]
    targets_f = [f"fwd_path_h{h}" for h in HORIZONS] + [f"fwd_vol_h{h}" for h in HORIZONS]
    table_f = ic_table(panel, predictors_f, targets_f)
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(table_f.to_string(index=False))

    # === Side-by-side: does wedge predict path differently than vol? ===
    print("\n" + "=" * 70)
    print(" Side-by-side: wedge_ewma IC against PATH vs VOL targets")
    print("=" * 70)
    rows = []
    for h in HORIZONS:
        sub = panel.dropna(subset=["vrp_wedge_ewma",
                                    f"fwd_vol_h{h}", f"fwd_path_h{h}"])
        if len(sub) < 1000:
            continue
        ic_vol  = float(sub["vrp_wedge_ewma"].corr(sub[f"fwd_vol_h{h}"], method="spearman"))
        ic_path = float(sub["vrp_wedge_ewma"].corr(sub[f"fwd_path_h{h}"], method="spearman"))
        rows.append({"horizon": h, "n": len(sub),
                     "ic_wedge_vs_fwd_vol": ic_vol,
                     "ic_wedge_vs_fwd_path": ic_path,
                     "delta_path_minus_vol": ic_path - ic_vol})
    cmp = pd.DataFrame(rows)
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(cmp.to_string(index=False))

    # Save outputs
    out_path = OUT_DIR / "vrp_residual_path.csv"
    pd.concat([table_e.assign(test="E"), table_f.assign(test="F"),
               cmp.assign(test="vs_path")], ignore_index=True).to_csv(out_path, index=False)
    print(f"\n[E_F] Wrote results to {out_path}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

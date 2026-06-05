"""
vrp_ic_yz.py — Re-run the corpus VRP IC suite with Yang-Zhang forward vol
                as the dependent variable (vs the existing GK close-to-close std).

Mirrors vrp_ic.py exactly except for one change: forward vol is computed as YZ
(includes overnight gaps + Rogers-Satchell intraday + open-to-close) rather than
log-return std (intraday close-to-close only, equivalent to GK).

If YZ gives meaningfully higher IC than GK across the 8-predictor × 4-metric ×
3-horizon grid, the dependent-variable upgrade is validated and we should
migrate `features.py` to use YZ for `rv_*` columns and the prediction target.

Outputs:
  results/validation/vrp_ic_yz.csv
  results/validation/vrp_ic_yz_summary.md
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

HORIZONS = (21, 63, 126)
METRICS = ("vol",)  # focus on vol (the central question); skip ret/dd/absret for this comparison
PREDICTORS = ("vrp_raw", "vrp_ewma", "vrp_pct_own", "vrp_ewma_pct_own",
              "vrp_zscore_own", "vrp_slope5", "vrp_ewma_slope5", "vrp_sign")
ROLLING_WINDOW = 252
EWMA_HALFLIFE = 21
MIN_OBS_FOR_IC_POOLED = 200
MIN_OBS_FOR_IC_PERTICKER = 100


def load_vrp_per_ticker() -> dict[str, pd.DataFrame]:
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
        out[ticker] = df
    return out


def add_predictors(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().sort_values("date").reset_index(drop=True)
    v = df["vrp_wedge"]
    df["vrp_raw"] = v
    df["vrp_ewma"] = v.ewm(halflife=EWMA_HALFLIFE, adjust=False).mean()
    df["vrp_sign"] = (v > 0).astype(int)
    df["vrp_pct_own"] = v.rolling(ROLLING_WINDOW, min_periods=63).apply(
        lambda x: (x.rank().iloc[-1] - 1) / max(len(x) - 1, 1), raw=False)
    df["vrp_ewma_pct_own"] = df["vrp_ewma"].rolling(
        ROLLING_WINDOW, min_periods=63).apply(
        lambda x: (x.rank().iloc[-1] - 1) / max(len(x) - 1, 1), raw=False)
    rmean = v.rolling(ROLLING_WINDOW, min_periods=63).mean()
    rstd  = v.rolling(ROLLING_WINDOW, min_periods=63).std()
    df["vrp_zscore_own"] = (v - rmean) / rstd.replace(0, np.nan)
    df["vrp_slope5"]      = v.diff(5) / 5.0
    df["vrp_ewma_slope5"] = df["vrp_ewma"].diff(5) / 5.0
    return df


def load_ohlcv() -> pd.DataFrame:
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    ohlcv = store.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    # Normalize column names
    rename = {"openprc": "open", "askhi": "high", "bidlo": "low", "prc": "close"}
    for k, v in rename.items():
        if k in ohlcv.columns and v not in ohlcv.columns:
            ohlcv = ohlcv.rename(columns={k: v})
    for col in ("open", "high", "low", "close"):
        if col in ohlcv.columns:
            ohlcv[col] = ohlcv[col].abs()
    return ohlcv


def yang_zhang_vol_window(o: np.ndarray, h: np.ndarray, l: np.ndarray,
                           c: np.ndarray, c_prev_first: float) -> float:
    """YZ vol over a single forward window of n=len(c) bars. Annualized."""
    n = len(c)
    if n < 3 or not np.isfinite(o).all() or not np.isfinite(h).all() \
            or not np.isfinite(l).all() or not np.isfinite(c).all():
        return np.nan
    # Overnight returns: ln(O_t / C_{t-1})
    c_lagged = np.concatenate(([c_prev_first], c[:-1]))
    if not np.isfinite(c_prev_first):
        return np.nan
    ln_oc = np.log(o / c_lagged)
    ln_co = np.log(c / o)
    rs = np.log(h / c) * np.log(h / o) + np.log(l / c) * np.log(l / o)
    # Sample variances (drift-removed by ddof=1)
    sigma2_o  = float(np.var(ln_oc, ddof=1))
    sigma2_co = float(np.var(ln_co, ddof=1))
    sigma2_rs = float(np.mean(rs))
    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    sigma2_yz = sigma2_o + k * sigma2_co + (1 - k) * sigma2_rs
    if not np.isfinite(sigma2_yz) or sigma2_yz <= 0:
        return np.nan
    return float(np.sqrt(sigma2_yz) * np.sqrt(252))


def add_forward_outcomes_yz(df: pd.DataFrame, ticker: str,
                             ohlcv_pivots: dict) -> pd.DataFrame:
    """Forward YZ vol per row, at each horizon."""
    if ticker not in ohlcv_pivots["close"].columns:
        return df
    o = ohlcv_pivots["open"][ticker]
    h = ohlcv_pivots["high"][ticker]
    l = ohlcv_pivots["low"][ticker]
    c = ohlcv_pivots["close"][ticker]
    # Index where we look up each snap
    df = df.copy().reset_index(drop=True)

    snap_idx = np.full(len(df), -1, dtype=int)
    for i, d in enumerate(df["date"].values):
        d = pd.Timestamp(d)
        idx = c.index.searchsorted(d, side="right") - 1
        if 0 <= idx < len(c):
            snap_idx[i] = idx
    df["snap_idx"] = snap_idx

    for horizon in HORIZONS:
        fwd_yz = np.full(len(df), np.nan)
        for i in range(len(df)):
            idx = snap_idx[i]
            if idx < 0:
                continue
            j_start = idx + 1
            j_end   = idx + horizon
            if j_end >= len(c):
                continue
            o_w = o.iloc[j_start:j_end + 1].values
            h_w = h.iloc[j_start:j_end + 1].values
            l_w = l.iloc[j_start:j_end + 1].values
            c_w = c.iloc[j_start:j_end + 1].values
            c_prev_first = c.iloc[idx] if idx >= 0 else np.nan
            fwd_yz[i] = yang_zhang_vol_window(o_w, h_w, l_w, c_w, c_prev_first)
        df[f"fwd_yz_h{horizon}"] = fwd_yz
    df = df.drop(columns=["snap_idx"])
    return df


def pooled_ic(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for pred in PREDICTORS:
        for h in HORIZONS:
            col = f"fwd_yz_h{h}"
            if col not in df.columns:
                continue
            sub = df.dropna(subset=[pred, col])
            if len(sub) < MIN_OBS_FOR_IC_POOLED:
                continue
            ic = float(sub[pred].corr(sub[col], method="spearman"))
            rows.append({"predictor": pred, "horizon": h,
                         "n": len(sub), "ic_pooled_yz": ic})
    return pd.DataFrame(rows)


def perticker_ic(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for pred in PREDICTORS:
        for h in HORIZONS:
            col = f"fwd_yz_h{h}"
            if col not in df.columns:
                continue
            ics = []
            for tk, g in df.groupby("ticker"):
                sub = g.dropna(subset=[pred, col])
                if len(sub) < MIN_OBS_FOR_IC_PERTICKER:
                    continue
                ic = float(sub[pred].corr(sub[col], method="spearman"))
                if np.isfinite(ic):
                    ics.append(ic)
            if len(ics) < 10:
                continue
            ics = np.asarray(ics)
            rows.append({"predictor": pred, "horizon": h,
                         "n_tickers": int(len(ics)),
                         "ic_median_yz": float(np.median(ics)),
                         "ic_mean_yz": float(np.mean(ics)),
                         "frac_abs_above_010_yz": float(np.mean(np.abs(ics) > 0.10))})
    return pd.DataFrame(rows)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[VRP_IC_YZ] Loading per-ticker predictions...")
    per_t = load_vrp_per_ticker()
    print(f"  {len(per_t)} tickers")

    print("[VRP_IC_YZ] Adding predictor features...")
    for tk in per_t:
        per_t[tk] = add_predictors(per_t[tk])

    print("[VRP_IC_YZ] Loading OHLCV + pivoting...")
    ohlcv = load_ohlcv()
    needed = ("open", "high", "low", "close")
    pivots = {col: ohlcv.drop_duplicates(subset=["date", "ticker"], keep="last")
                       .pivot(index="date", columns="ticker", values=col).ffill()
              for col in needed}

    print("[VRP_IC_YZ] Computing forward YZ vol per ticker (per-row YZ on rolling window)...")
    pieces = []
    for i, tk in enumerate(sorted(per_t), 1):
        d = add_forward_outcomes_yz(per_t[tk], tk, pivots)
        d["ticker"] = tk
        pieces.append(d)
        if i % 20 == 0:
            print(f"  {i}/{len(per_t)}")
    full = pd.concat(pieces, ignore_index=True)
    print(f"[VRP_IC_YZ] {len(full):,} observations")

    print("[VRP_IC_YZ] Computing pooled IC...")
    pooled = pooled_ic(full)
    pooled.to_csv(OUT_DIR / "vrp_ic_yz.csv", index=False)

    print("[VRP_IC_YZ] Computing per-ticker IC...")
    perticker = perticker_ic(full)
    perticker.to_csv(OUT_DIR / "vrp_ic_yz_perticker.csv", index=False)

    # Load the original GK results for side-by-side
    gk_path = OUT_DIR / "vrp_ic.csv"
    perticker_gk_path = OUT_DIR / "vrp_ic_perticker.csv"
    if gk_path.exists():
        gk_pooled = pd.read_csv(gk_path)
        gk_pooled = gk_pooled[gk_pooled["metric"] == "vol"]
    else:
        gk_pooled = pd.DataFrame()

    print("\n=== POOLED IC: GK vs YZ (forward vol target), all 8 predictors ===")
    cmp = pooled.pivot_table(index="predictor", columns="horizon",
                              values="ic_pooled_yz").reset_index()
    if not gk_pooled.empty:
        gk_piv = gk_pooled.pivot_table(index="predictor", columns="horizon",
                                        values="ic_pooled").reset_index()
        merged = cmp.merge(gk_piv, on="predictor", suffixes=("_yz", "_gk"))
        # Reorder columns: predictor, h21_gk, h21_yz, h63_gk, h63_yz, h126_gk, h126_yz
        cols = ["predictor"]
        for h in HORIZONS:
            for tag in ("gk", "yz"):
                c = f"{h}_{tag}"
                if c in merged.columns:
                    cols.append(c)
                elif h in merged.columns and tag == "yz":
                    cols.append(h)
        # Just print whatever's there
        with pd.option_context("display.width", 200,
                               "display.float_format", lambda v: f"{v:+.3f}"):
            print(merged.to_string(index=False))
    else:
        with pd.option_context("display.width", 200,
                               "display.float_format", lambda v: f"{v:+.3f}"):
            print(cmp.to_string(index=False))

    # Compute and print explicit GK vs YZ delta per (predictor, horizon)
    if not gk_pooled.empty:
        print("\n=== Δ IC (YZ − GK), positive = YZ improves ===")
        delta_rows = []
        for pred in PREDICTORS:
            row = {"predictor": pred}
            for h in HORIZONS:
                yz = pooled[(pooled.predictor == pred) & (pooled.horizon == h)]
                gk = gk_pooled[(gk_pooled.predictor == pred) & (gk_pooled.horizon == h)]
                if not yz.empty and not gk.empty:
                    row[f"delta_h{h}"] = float(yz.iloc[0]["ic_pooled_yz"]) - float(gk.iloc[0]["ic_pooled"])
            delta_rows.append(row)
        with pd.option_context("display.width", 200,
                               "display.float_format", lambda v: f"{v:+.3f}"):
            print(pd.DataFrame(delta_rows).to_string(index=False))

    print("\n=== PER-TICKER MEDIAN IC (YZ), h=21 ===")
    sub = perticker[perticker.horizon == 21]
    out = sub[["predictor", "n_tickers", "ic_median_yz", "ic_mean_yz",
               "frac_abs_above_010_yz"]].sort_values("ic_median_yz", ascending=False)
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(out.to_string(index=False))

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

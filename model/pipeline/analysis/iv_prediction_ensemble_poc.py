"""
iv_prediction_ensemble_poc.py — Expanded IV-prediction POC with:
  1. Full ensemble (XGB + RF + ElasticNet, simple-average combination)
  2. 10 tickers (vs 5 in the original ElasticNet POC)
  3. Yang-Zhang realized vol as alternative dependent variable (alongside GK)
  4. NEW: Is `predicted_iv` a better forecaster of forward RV than `actual_iv`?

Methodology:
  - Train ensemble on data BEFORE 2025-05-27 (single train, no WFA — POC scope)
  - Predict every date from 2025-05-27 to 2026-05-27 (the last year)
  - Target: iv_atm_30d at date D
  - Features: 51 non-IV columns (rv_*, macro_*, factor_returns, technicals, etc.)

Outputs:
  results/validation/iv_pred_ensemble.csv
  prints per-ticker + pooled comparison
"""
from __future__ import annotations

from pathlib import Path

import warnings
import numpy as np
import pandas as pd
from sklearn.linear_model import ElasticNetCV
from sklearn.ensemble import RandomForestRegressor
from xgboost import XGBRegressor

warnings.filterwarnings("ignore")

from ..config import load_config
from ..data_loader import fetch_dataset, ParquetStore
from ..features import FeatureBuilder

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "validation"

POC_TICKERS = ["AAPL", "JPM", "XOM", "NVDA", "KO",
               "MSFT", "GS", "CVX", "AMD", "PG"]
TARGET_COL = "iv_atm_30d"
EXCLUDE_PATTERNS = ("iv_", "vrp_", "put_call", "term_structure", "iv_atm")
EVAL_CUTOFF = pd.Timestamp("2025-05-27")        # train on data before this; eval after
EWMA_HALFLIFE = 21
FWD_HORIZONS = (21, 63)
YZ_WINDOW = 21


def select_non_iv_predictors(feature_df: pd.DataFrame) -> list[str]:
    cols = []
    for c in feature_df.columns:
        s = feature_df[c]
        if not pd.api.types.is_numeric_dtype(s):
            continue
        cl = c.lower()
        if any(p in cl for p in EXCLUDE_PATTERNS):
            continue
        if cl.startswith("y_"):
            continue
        if cl in (TARGET_COL.lower(), "rv_target"):
            continue
        cols.append(c)
    return cols


def train_ensemble(X_tr: np.ndarray, y_tr: np.ndarray) -> tuple:
    """Simple-average ensemble of XGB + RF + ElasticNet."""
    xgb = XGBRegressor(n_estimators=200, max_depth=5, learning_rate=0.05,
                       tree_method="hist", device="cpu", n_jobs=4, verbosity=0)
    rf  = RandomForestRegressor(n_estimators=150, max_depth=10, n_jobs=4,
                                random_state=42)
    en  = ElasticNetCV(l1_ratio=[0.3, 0.5, 0.7, 0.9], cv=3, max_iter=10000,
                       n_jobs=4)
    xgb.fit(X_tr, y_tr)
    rf.fit(X_tr, y_tr)
    en.fit(X_tr, y_tr)
    return xgb, rf, en


def predict_ensemble(models: tuple, X: np.ndarray) -> np.ndarray:
    xgb, rf, en = models
    return (xgb.predict(X) + rf.predict(X) + en.predict(X)) / 3.0


def yang_zhang_vol(ohlc: pd.DataFrame, window: int = YZ_WINDOW) -> pd.Series:
    """Yang-Zhang (2000) volatility estimator. Drift-independent, uses overnight
    gaps + open-to-close + Rogers-Satchell intraday. Returns annualized vol
    (rolling window). Expects columns: open, high, low, close (lowercase)."""
    o = ohlc["open"].astype(float)
    h = ohlc["high"].astype(float)
    l = ohlc["low"].astype(float)
    c = ohlc["close"].astype(float)
    c_prev = c.shift(1)

    # Overnight return (close-to-open)
    ln_oc_prev = np.log(o / c_prev)
    # Open-to-close return
    ln_co = np.log(c / o)
    # Rogers-Satchell intraday
    rs = np.log(h / c) * np.log(h / o) + np.log(l / c) * np.log(l / o)

    # Rolling variances (sample variance, drift-corrected by demeaning)
    sigma2_o  = ln_oc_prev.rolling(window).var(ddof=1)
    sigma2_co = ln_co.rolling(window).var(ddof=1)
    sigma2_rs = rs.rolling(window).mean()

    # Optimal weight k (Yang-Zhang)
    n = window
    k = 0.34 / (1.34 + (n + 1) / (n - 1)) if n > 1 else 0.34

    sigma2_yz = sigma2_o + k * sigma2_co + (1 - k) * sigma2_rs
    sigma_yz_annual = np.sqrt(sigma2_yz.clip(lower=1e-12)) * np.sqrt(252)
    return sigma_yz_annual


def load_ohlc(ticker: str) -> pd.DataFrame | None:
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    ohlcv = store.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    sub = ohlcv[ohlcv["ticker"] == ticker].sort_values("date").drop_duplicates(
        subset=["date"], keep="last")
    if sub.empty:
        return None
    # Normalize column names
    rename = {"openprc": "open", "askhi": "high", "bidlo": "low", "prc": "close"}
    for k, v in rename.items():
        if k in sub.columns and v not in sub.columns:
            sub = sub.rename(columns={k: v})
    for col in ("open", "high", "low", "close"):
        if col in sub.columns:
            sub[col] = sub[col].abs()
    return sub.set_index("date")[["open", "high", "low", "close"]]


def forward_vol_series(close: pd.Series, h: int, method: str = "gk",
                        ohlc: pd.DataFrame | None = None) -> pd.Series:
    """Forward h-BD annualized realized vol. method='gk' uses log-return std;
    method='yz' uses Yang-Zhang on the full OHLC (requires ohlc)."""
    if method == "gk":
        log_ret = np.log(close).diff()
        fwd = log_ret.rolling(h).std().shift(-h) * np.sqrt(252)
        return fwd
    elif method == "yz":
        if ohlc is None:
            return pd.Series(dtype=float, index=close.index)
        yz_rolling = yang_zhang_vol(ohlc, window=h)
        # yz_rolling is BACKWARD-looking rolling window. Forward = shift by -h.
        return yz_rolling.shift(-h)
    else:
        raise ValueError(f"unknown method: {method}")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dc, mc, bc = load_config()

    print(f"[IV_ENS_POC] Loading dataset (cache as-is)...")
    raw = fetch_dataset(dc)
    builder = FeatureBuilder(dc, mc)

    summary_rows = []
    all_pred_rows = []

    for ticker in POC_TICKERS:
        print(f"\n[IV_ENS_POC] === {ticker} ===")
        try:
            fdf = builder.build(ticker, raw, drop_nan_targets=False)
        except Exception as e:
            print(f"  feature build failed: {e}")
            continue

        if TARGET_COL not in fdf.columns:
            print(f"  no {TARGET_COL} column")
            continue

        predictors = select_non_iv_predictors(fdf)
        df = fdf[predictors + [TARGET_COL, "vrp_wedge"]].copy()
        df.index = pd.to_datetime(df.index)
        df = df.dropna(subset=[TARGET_COL])

        # Train / eval split
        train_df = df[df.index <  EVAL_CUTOFF]
        eval_df  = df[df.index >= EVAL_CUTOFF]
        if len(train_df) < 500 or len(eval_df) < 20:
            print(f"  insufficient data (train={len(train_df)}, eval={len(eval_df)})")
            continue

        X_tr = train_df[predictors].ffill().bfill().fillna(0).values
        y_tr = train_df[TARGET_COL].values
        X_ev = eval_df[predictors].ffill().bfill().fillna(0).values

        print(f"  train: {len(train_df)} rows | eval: {len(eval_df)} rows | predictors: {len(predictors)}")
        print(f"  training XGB+RF+EN ensemble...")
        models = train_ensemble(X_tr, y_tr)
        print(f"  predicting eval window...")
        y_pred = predict_ensemble(models, X_ev)

        # Build OOS frame
        oos = pd.DataFrame({
            "date": eval_df.index,
            "actual_iv": eval_df[TARGET_COL].values,
            "predicted_iv": y_pred,
            "vrp_wedge_classical": eval_df["vrp_wedge"].values,
        })

        # Load OHLC for YZ vol
        ohlc = load_ohlc(ticker)
        if ohlc is None:
            print(f"  no OHLC data — skipping YZ comparison")
            continue
        close = ohlc["close"]

        # Forward vol targets: GK (standard log-return std) and YZ
        fwd_gk_h21 = forward_vol_series(close, 21, method="gk")
        fwd_gk_h63 = forward_vol_series(close, 63, method="gk")
        fwd_yz_h21 = forward_vol_series(close, 21, method="yz", ohlc=ohlc)
        fwd_yz_h63 = forward_vol_series(close, 63, method="yz", ohlc=ohlc)

        oos = oos.set_index("date")
        oos["fwd_gk_h21"] = fwd_gk_h21
        oos["fwd_gk_h63"] = fwd_gk_h63
        oos["fwd_yz_h21"] = fwd_yz_h21
        oos["fwd_yz_h63"] = fwd_yz_h63
        oos = oos.reset_index()

        # Wedges
        oos["wedge_new"]       = oos["actual_iv"] - oos["predicted_iv"]
        oos["wedge_classical"] = oos["vrp_wedge_classical"]

        # EWMA smoothed
        oos = oos.sort_values("date").reset_index(drop=True)
        for col in ("wedge_new", "wedge_classical", "actual_iv", "predicted_iv"):
            oos[f"{col}_ewma"] = oos[col].ewm(halflife=EWMA_HALFLIFE, adjust=False).mean()

        oos["ticker"] = ticker
        all_pred_rows.append(oos)

        # Per-ticker ICs
        row = {"ticker": ticker, "n_obs": int(oos["wedge_new"].notna().sum())}
        for h in FWD_HORIZONS:
            for vol_kind in ("gk", "yz"):
                tgt = f"fwd_{vol_kind}_h{h}"
                sub = oos.dropna(subset=["wedge_new_ewma", "wedge_classical_ewma", tgt])
                if len(sub) < 30:
                    continue
                row[f"ic_classical_{vol_kind}_h{h}"] = float(sub["wedge_classical_ewma"].corr(sub[tgt], method="spearman"))
                row[f"ic_new_{vol_kind}_h{h}"]       = float(sub["wedge_new_ewma"].corr(sub[tgt], method="spearman"))

                # NEW: is predicted_iv a better RV forecaster than actual_iv?
                row[f"ic_pred_iv_as_rv_pred_{vol_kind}_h{h}"]   = float(sub["predicted_iv_ewma"].corr(sub[tgt], method="spearman"))
                row[f"ic_actual_iv_as_rv_pred_{vol_kind}_h{h}"] = float(sub["actual_iv_ewma"].corr(sub[tgt], method="spearman"))

        summary_rows.append(row)
        print(f"  IC classical vs fwd_gk_h21: {row.get('ic_classical_gk_h21', np.nan):+.3f}")
        print(f"  IC new       vs fwd_gk_h21: {row.get('ic_new_gk_h21', np.nan):+.3f}")
        print(f"  predicted_iv vs fwd_gk_h21: {row.get('ic_pred_iv_as_rv_pred_gk_h21', np.nan):+.3f}")
        print(f"  actual_iv    vs fwd_gk_h21: {row.get('ic_actual_iv_as_rv_pred_gk_h21', np.nan):+.3f}")

    if not summary_rows:
        print("[IV_ENS_POC] No tickers produced results.")
        return 1

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(OUT_DIR / "iv_pred_ensemble_per_ticker.csv", index=False)

    full = pd.concat(all_pred_rows, ignore_index=True)
    full.to_csv(OUT_DIR / "iv_pred_ensemble_raw.csv", index=False)

    # === PRINTING ===
    print("\n" + "=" * 80)
    print(" PER-TICKER IC — wedge vs forward vol (GK), H=21")
    print("=" * 80)
    cols = ["ticker", "n_obs", "ic_classical_gk_h21", "ic_new_gk_h21"]
    avail_cols = [c for c in cols if c in summary_df.columns]
    out = summary_df[avail_cols].copy()
    out["delta"] = out["ic_new_gk_h21"] - out["ic_classical_gk_h21"]
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(out.to_string(index=False))

    print("\n" + "=" * 80)
    print(" PER-TICKER: is predicted_iv a better RV forecaster than actual market IV?")
    print(" (Spearman IC of {predicted,actual}_iv_ewma vs forward GK vol, H=21)")
    print("=" * 80)
    cols = ["ticker", "ic_actual_iv_as_rv_pred_gk_h21", "ic_pred_iv_as_rv_pred_gk_h21"]
    avail_cols = [c for c in cols if c in summary_df.columns]
    out = summary_df[avail_cols].copy()
    out["delta_pred_minus_actual"] = (out["ic_pred_iv_as_rv_pred_gk_h21"]
                                       - out["ic_actual_iv_as_rv_pred_gk_h21"])
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(out.to_string(index=False))

    print("\n" + "=" * 80)
    print(" PER-TICKER: wedge IC vs YZ forward vol (vs GK) — same wedge, different target")
    print("=" * 80)
    cols = ["ticker", "ic_classical_gk_h21", "ic_classical_yz_h21",
            "ic_new_gk_h21", "ic_new_yz_h21"]
    avail_cols = [c for c in cols if c in summary_df.columns]
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(summary_df[avail_cols].to_string(index=False))

    # Pooled across all tickers
    print("\n=== POOLED IC across all tickers ===")
    for h in FWD_HORIZONS:
        for kind in ("gk", "yz"):
            tgt = f"fwd_{kind}_h{h}"
            if tgt not in full.columns:
                continue
            sub = full.dropna(subset=["wedge_new_ewma", "wedge_classical_ewma",
                                       "actual_iv_ewma", "predicted_iv_ewma", tgt])
            if len(sub) < 100:
                continue
            ic_c = float(sub["wedge_classical_ewma"].corr(sub[tgt], method="spearman"))
            ic_n = float(sub["wedge_new_ewma"].corr(sub[tgt], method="spearman"))
            ic_actual_iv = float(sub["actual_iv_ewma"].corr(sub[tgt], method="spearman"))
            ic_pred_iv   = float(sub["predicted_iv_ewma"].corr(sub[tgt], method="spearman"))
            print(f"  h={h:3d} ({kind}): classical={ic_c:+.3f}  new={ic_n:+.3f}  "
                  f"actual_iv→rv={ic_actual_iv:+.3f}  pred_iv→rv={ic_pred_iv:+.3f}  "
                  f"(n={len(sub):,})")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

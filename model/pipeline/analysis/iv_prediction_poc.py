"""
iv_prediction_poc.py — Predict iv_atm_30d from NON-IV features, compute the
                       cleaner wedge: actual IV minus our IV prediction.

Per RESEARCH_TODO §11. The classical vrp_wedge mixes statistical RV with
market-priced IV. By instead predicting IV itself from realized/macro/technical
features (excluding all options-derived inputs), the wedge becomes pure
"options market disagrees with our IV baseline" — single conceptual axis.

POC scope: 5 tickers, ElasticNet WFA at quarterly cadence. Compares the
new wedge's IC vs the classical wedge's IC against forward outcomes.

Outputs:
  results/validation/iv_prediction_poc.csv
  prints headline comparison table
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import ElasticNetCV
import warnings
warnings.filterwarnings("ignore")

from ..config import load_config
from ..data_loader import fetch_dataset, ParquetStore
from ..features import FeatureBuilder

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "validation"

POC_TICKERS = ["AAPL", "JPM", "XOM", "NVDA", "KO"]
TARGET_COL = "iv_atm_30d"
# Patterns to EXCLUDE from predictors (anything options-market derived)
EXCLUDE_PATTERNS = ("iv_", "vrp_", "put_call", "term_structure", "iv_atm")
STEP_BD = 60                     # quarterly WFA
MIN_TRAIN = 504                  # 2 years before first prediction
EWMA_HALFLIFE = 21
FWD_HORIZONS = (21, 63)


def select_non_iv_predictors(feature_df: pd.DataFrame) -> list[str]:
    """All numeric columns that aren't options-derived and aren't targets/etc."""
    cols = []
    for c in feature_df.columns:
        s = feature_df[c]
        if not pd.api.types.is_numeric_dtype(s):
            continue
        cl = c.lower()
        if any(p in cl for p in EXCLUDE_PATTERNS):
            continue
        if cl.startswith("y_"):       # backtest target columns
            continue
        if cl in (TARGET_COL.lower(), "rv_target"):
            continue
        cols.append(c)
    return cols


def wfa_iv_predict(feature_df: pd.DataFrame, predictors: list[str]) -> pd.DataFrame:
    """ElasticNet WFA: walk forward in STEP_BD chunks, retrain each step,
    predict next chunk. Returns (date, actual_iv, predicted_iv) for OOS rows."""
    df = feature_df.copy()
    df = df.dropna(subset=[TARGET_COL])
    if len(df) < MIN_TRAIN + STEP_BD:
        return pd.DataFrame()

    out_rows = []
    cutoff_idx = MIN_TRAIN
    while cutoff_idx < len(df):
        train = df.iloc[:cutoff_idx]
        pred_chunk = df.iloc[cutoff_idx:cutoff_idx + STEP_BD]
        if pred_chunk.empty:
            break

        X_tr = train[predictors].ffill().bfill().fillna(0).values
        y_tr = train[TARGET_COL].values
        X_pr = pred_chunk[predictors].ffill().bfill().fillna(0).values

        try:
            mdl = ElasticNetCV(l1_ratio=[0.3, 0.5, 0.7, 0.9],
                                cv=3, max_iter=10000, n_jobs=1)
            mdl.fit(X_tr, y_tr)
            y_pred = mdl.predict(X_pr)
        except Exception as e:
            print(f"    train fail at idx {cutoff_idx}: {e}")
            cutoff_idx += STEP_BD
            continue

        for i, idx in enumerate(pred_chunk.index):
            out_rows.append({"date": idx,
                             "actual_iv": float(pred_chunk[TARGET_COL].iloc[i]),
                             "predicted_iv": float(y_pred[i])})
        cutoff_idx += STEP_BD

    return pd.DataFrame(out_rows)


def load_spy_close_for_fwd_vol() -> pd.Series:
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    ohlcv = store.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    return ohlcv.pivot_table(index="date", columns="ticker",
                              values="prc", aggfunc="last").ffill()


def per_ticker_fwd_vol(closes: pd.DataFrame, ticker: str,
                        h: int) -> pd.Series:
    if ticker not in closes.columns:
        return pd.Series(dtype=float)
    s = closes[ticker].dropna()
    log_ret = np.log(s).diff()
    # Realized vol over next h BD (forward): use rolling and shift
    fwd = log_ret.rolling(h).std().shift(-h) * np.sqrt(252)
    return fwd


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dc, mc, bc = load_config()
    print(f"[IV_POC] Loading dataset (cache as-is)...")
    raw = fetch_dataset(dc)
    builder = FeatureBuilder(dc, mc)

    print(f"[IV_POC] Loading closes for forward-vol target...")
    closes = load_spy_close_for_fwd_vol()

    all_rows = []
    summary = []
    for ticker in POC_TICKERS:
        print(f"\n[IV_POC] {ticker}: building features...")
        try:
            fdf = builder.build(ticker, raw, drop_nan_targets=False)
        except Exception as e:
            print(f"  feature build failed: {e}")
            continue

        if TARGET_COL not in fdf.columns:
            print(f"  no {TARGET_COL} column; skipping")
            continue

        predictors = select_non_iv_predictors(fdf)
        print(f"  {len(predictors)} non-IV predictors selected")
        print(f"  feature history: {len(fdf)} rows, target valid: {fdf[TARGET_COL].notna().sum()}")

        preds = wfa_iv_predict(fdf, predictors)
        if preds.empty:
            print(f"  insufficient history for WFA")
            continue
        print(f"  OOS predictions: {len(preds)} rows from {preds['date'].min().date()}")

        # Attach classical vrp_wedge by joining on date index
        keep_cols = ["vrp_wedge"]
        if "rv_TARGET" in fdf.columns:
            keep_cols.append("rv_TARGET")
        elif "rv_21d" in fdf.columns:
            keep_cols.append("rv_21d")
        wedge_lookup = fdf[keep_cols].copy()
        wedge_lookup.index.name = "date"
        wedge_lookup = wedge_lookup.reset_index()
        preds["date"] = pd.to_datetime(preds["date"])
        wedge_lookup["date"] = pd.to_datetime(wedge_lookup["date"])
        preds = preds.merge(wedge_lookup, on="date", how="left")

        preds["wedge_new"]       = preds["actual_iv"] - preds["predicted_iv"]
        preds["wedge_classical"] = preds["vrp_wedge"]

        # EWMAs
        preds = preds.sort_values("date").reset_index(drop=True)
        preds["wedge_new_ewma"]       = preds["wedge_new"].ewm(halflife=EWMA_HALFLIFE, adjust=False).mean()
        preds["wedge_classical_ewma"] = preds["wedge_classical"].ewm(halflife=EWMA_HALFLIFE, adjust=False).mean()

        # Forward vol per horizon, joined by date
        for h in FWD_HORIZONS:
            fwd = per_ticker_fwd_vol(closes, ticker, h)
            preds[f"fwd_vol_h{h}"] = preds["date"].map(fwd)

        preds["ticker"] = ticker
        all_rows.append(preds)

        # Per-ticker ICs
        row = {"ticker": ticker, "n_obs": int(preds["wedge_new"].notna().sum())}
        for h in FWD_HORIZONS:
            tgt = f"fwd_vol_h{h}"
            sub = preds.dropna(subset=["wedge_new_ewma", "wedge_classical_ewma", tgt])
            if len(sub) < 50:
                row[f"ic_classical_h{h}"] = np.nan
                row[f"ic_new_h{h}"]       = np.nan
                continue
            row[f"ic_classical_h{h}"] = float(sub["wedge_classical_ewma"].corr(sub[tgt], method="spearman"))
            row[f"ic_new_h{h}"]       = float(sub["wedge_new_ewma"].corr(sub[tgt], method="spearman"))
            row[f"delta_h{h}"]        = row[f"ic_new_h{h}"] - row[f"ic_classical_h{h}"]
        summary.append(row)
        print(f"  IC classical h=21: {row.get('ic_classical_h21', np.nan):+.3f}")
        print(f"  IC new       h=21: {row.get('ic_new_h21', np.nan):+.3f}")
        print(f"  Delta        h=21: {row.get('delta_h21', np.nan):+.3f}")

    if not summary:
        print("[IV_POC] No tickers produced results.")
        return 1

    summary_df = pd.DataFrame(summary)
    summary_df.to_csv(OUT_DIR / "iv_prediction_poc_per_ticker.csv", index=False)

    full = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    full.to_csv(OUT_DIR / "iv_prediction_poc_raw.csv", index=False)

    print("\n" + "=" * 70)
    print(" Per-ticker IC comparison: NEW wedge (IV-prediction) vs CLASSICAL")
    print("=" * 70)
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        cols = ["ticker", "n_obs"] + [
            c for c in summary_df.columns
            if c.startswith("ic_") or c.startswith("delta_")
        ]
        print(summary_df[cols].to_string(index=False))

    # Pooled IC across all 5 tickers
    print("\n=== POOLED IC (all 5 tickers concatenated) ===")
    for h in FWD_HORIZONS:
        tgt = f"fwd_vol_h{h}"
        if tgt not in full.columns:
            continue
        sub = full.dropna(subset=["wedge_new_ewma", "wedge_classical_ewma", tgt])
        if len(sub) < 100:
            continue
        ic_c = float(sub["wedge_classical_ewma"].corr(sub[tgt], method="spearman"))
        ic_n = float(sub["wedge_new_ewma"].corr(sub[tgt], method="spearman"))
        print(f"  h={h:3d}: classical={ic_c:+.3f}  new={ic_n:+.3f}  "
              f"delta={ic_n-ic_c:+.3f}  (n={len(sub):,})")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

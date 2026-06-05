"""
vrp_har_baseline_compare.py -- HAR-RV head-to-head vs our ML ensemble for the
                               forward VRP construction.

HAR-RV (Corsi 2009) is the strongest simple physical-RV forecasting baseline:
  y_true_21(t) = b0 + b_d*RV_1d(t) + b_w*RV_5d(t) + b_m*RV_21d(t) + e

Per ticker, walk-forward fit (expanding window, retrain every 21 BD, 252-BD min
training, 21-BD label purge so the latest training label's forward window
doesn't reach the prediction date). Same cadence as our ensemble. Daily GK
realized vol from OHLCV (high/low/open/close).

Then we run the same premium-share decomposition on:
  - ensemble model premium  (IV - y_pred_ensemble)
  - HAR     model premium  (IV - y_pred_HAR)
both against the same ex-post premium (IV - y_true).

Reports head-to-head: bias, RMSE, true-premium share, variance share.
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
from .beta_mz_deep_dive import RESULTS_DIR
from .vrp_forward_premium_test import build_panel

OUT_DIR = RESULTS_DIR / "validation"
RETRAIN_STEP = 21
MIN_TRAIN = 252
PURGE = 21


def daily_gk_rv(ohlc: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker daily Garman-Klass var -> trailing RV at 1/5/21 day windows."""
    h, lo, c, o = ohlc["askhi"], ohlc["bidlo"], ohlc["prc"], ohlc["openprc"]
    valid = (h > 0) & (lo > 0) & (c > 0) & (o > 0)
    gk = np.where(valid,
                  0.5 * (np.log(h / lo)) ** 2
                  - (2 * np.log(2) - 1) * (np.log(c / o)) ** 2,
                  np.nan)
    gk = pd.Series(gk, index=ohlc.index).clip(lower=0)
    out = pd.DataFrame(index=ohlc.index)
    out["rv_1d"] = np.sqrt(gk * 252)
    out["rv_5d"] = np.sqrt(gk.rolling(5).mean() * 252)
    out["rv_21d"] = np.sqrt(gk.rolling(21).mean() * 252)
    return out


def har_walk_forward(rv_df: pd.DataFrame, y_true_series: pd.Series,
                     retrain_step: int = RETRAIN_STEP,
                     min_train: int = MIN_TRAIN, purge: int = PURGE) -> pd.Series:
    """Walk-forward HAR predictions for one ticker. y_true_series indexed by date."""
    common = rv_df.index.intersection(y_true_series.index)
    df = rv_df.loc[common].copy()
    df["y"] = y_true_series.loc[common]
    df = df.dropna()
    n = len(df)
    preds = pd.Series(np.nan, index=df.index, dtype=float)
    feat_cols = ["rv_1d", "rv_5d", "rv_21d"]
    for i in range(min_train, n, retrain_step):
        if i - purge < min_train:
            continue
        train = df.iloc[:i - purge]
        Xtr = np.column_stack([np.ones(len(train)), train[feat_cols].to_numpy(float)])
        ytr = train["y"].to_numpy(float)
        try:
            beta, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)
        except Exception:
            continue
        end = min(i + retrain_step, n)
        Xpred = np.column_stack([np.ones(end - i),
                                  df.iloc[i:end][feat_cols].to_numpy(float)])
        preds.iloc[i:end] = Xpred @ beta
    return preds


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[VRP_HAR] Loading panel (ensemble preds, IV, y_true)...")
    p = build_panel()
    p = p[np.isfinite(p["iv"]) & np.isfinite(p["y_pred"]) & np.isfinite(p["y_true"])].copy()

    print("[VRP_HAR] Loading OHLCV + computing daily GK RV per ticker...")
    dc, _, _ = load_config()
    oh = ParquetStore(dc.base_dir).load("ohlcv")
    oh["date"] = pd.to_datetime(oh["date"], format="mixed")
    rv_panel = {}
    for tk, g in oh.drop_duplicates(["date", "ticker"]).groupby("ticker", observed=True):
        s = g.sort_values("date").set_index("date")[["askhi", "bidlo", "prc", "openprc"]]
        rv_panel[tk] = daily_gk_rv(s)

    print(f"[VRP_HAR] Walk-forward HAR per ticker (retrain every {RETRAIN_STEP} BD, "
          f"min_train={MIN_TRAIN}, purge={PURGE})...")
    har_rows = []
    for tk, sub in p.groupby("ticker"):
        if tk not in rv_panel:
            continue
        y_true_s = sub.set_index("date")["y_true"].sort_index()
        preds = har_walk_forward(rv_panel[tk], y_true_s)
        for d, v in preds.dropna().items():
            har_rows.append({"ticker": tk, "date": d, "y_pred_har": float(v)})
    har_df = pd.DataFrame(har_rows)
    print(f"  HAR predictions: {len(har_df):,}")

    pp = p.merge(har_df, on=["ticker", "date"], how="inner")
    print(f"  joined panel: {len(pp):,} rows ({pp['ticker'].nunique()} tickers)")
    pp["bias_ens"] = pp["y_true"] - pp["y_pred"]
    pp["bias_har"] = pp["y_true"] - pp["y_pred_har"]
    pp["err2_ens"] = pp["bias_ens"] ** 2
    pp["err2_har"] = pp["bias_har"] ** 2
    pp["model_prem_ens"] = pp["iv"] - pp["y_pred"]
    pp["model_prem_har"] = pp["iv"] - pp["y_pred_har"]
    pp["expost_prem"] = pp["iv"] - pp["y_true"]

    # ── Forecast accuracy head-to-head ───────────────────────────────────────
    print("\n" + "=" * 78)
    print(" FORECAST ACCURACY -- our ENSEMBLE vs HAR-RV (same OOS sample)")
    print("=" * 78)
    mb_ens = pp["bias_ens"].mean();  mb_har = pp["bias_har"].mean()
    rmse_ens = float(np.sqrt(pp["err2_ens"].mean()))
    rmse_har = float(np.sqrt(pp["err2_har"].mean()))
    mae_ens = float(pp["bias_ens"].abs().mean())
    mae_har = float(pp["bias_har"].abs().mean())
    print(f"  mean bias  (realized - forecast):  ensemble {mb_ens:+.4f}   HAR {mb_har:+.4f}")
    print(f"  RMSE                            :  ensemble {rmse_ens:.4f}    HAR {rmse_har:.4f}    "
          f"(ensemble {'wins' if rmse_ens<rmse_har else 'loses'} by "
          f"{(rmse_har-rmse_ens)/rmse_har*100:+.1f}%)")
    print(f"  MAE                             :  ensemble {mae_ens:.4f}    HAR {mae_har:.4f}    "
          f"(ensemble {'wins' if mae_ens<mae_har else 'loses'} by "
          f"{(mae_har-mae_ens)/mae_har*100:+.1f}%)")

    # ── Premium decomposition head-to-head ──────────────────────────────────
    print("\n" + "=" * 78)
    print(" PREMIUM-SHARE DECOMPOSITION (ensemble vs HAR as the E[RV] choice)")
    print("=" * 78)
    m_exp = float(pp["expost_prem"].mean())
    m_ens = float(pp["model_prem_ens"].mean())
    m_har = float(pp["model_prem_har"].mean())
    s_ens = m_exp / m_ens if m_ens else np.nan
    s_har = m_exp / m_har if m_har else np.nan
    print(f"  mean ex-post premium (IV - y_true):                 {m_exp:+.4f}  (the TRUE premium)")
    print(f"  mean model premium (IV - y_pred_ENSEMBLE):          {m_ens:+.4f}  -> "
          f"share of TRUE premium {s_ens:.0%}  (bias inflation {1-s_ens:.0%})")
    print(f"  mean model premium (IV - y_pred_HAR     ):          {m_har:+.4f}  -> "
          f"share of TRUE premium {s_har:.0%}  (bias inflation {1-s_har:.0%})")

    # ── Variance decomposition for each ─────────────────────────────────────
    print("\n" + "=" * 78)
    print(" VARIANCE SHARE -- of displayed premium variance, what's premium vs noise?")
    print("=" * 78)
    for label, prem_col, bias_col in [("ENSEMBLE", "model_prem_ens", "bias_ens"),
                                      ("HAR     ", "model_prem_har", "bias_har")]:
        v_mod = float(pp[prem_col].var())
        v_exp = float(pp["expost_prem"].var())
        v_fb = float(pp[bias_col].var())
        print(f"  {label}: var(model)={v_mod:.5f}  var(expost)={v_exp:.5f} ({v_exp/v_mod:.0%})  "
              f"var(bias)={v_fb:.5f} ({v_fb/v_mod:.0%})")

    # ── Per-ticker breadth (does either dominate ticker-by-ticker?) ─────────
    print("\n" + "=" * 78)
    print(" PER-TICKER BREADTH (RMSE comparison ticker-by-ticker)")
    print("=" * 78)
    pt = pp.groupby("ticker").apply(
        lambda d: pd.Series({"rmse_ens": float(np.sqrt(d["err2_ens"].mean())),
                              "rmse_har": float(np.sqrt(d["err2_har"].mean())),
                              "bias_ens": float(d["bias_ens"].mean()),
                              "bias_har": float(d["bias_har"].mean())}),
        include_groups=False)
    wins_ens = float((pt["rmse_ens"] < pt["rmse_har"]).mean())
    print(f"  ensemble RMSE < HAR RMSE on {wins_ens:.0%} of {len(pt)} tickers")
    print(f"  per-ticker mean bias |ensemble| < |HAR| on "
          f"{float((pt['bias_ens'].abs() < pt['bias_har'].abs()).mean()):.0%} of tickers")

    pp.to_csv(OUT_DIR / "vrp_har_baseline_compare.csv", index=False)
    pt.to_csv(OUT_DIR / "vrp_har_baseline_per_ticker.csv")
    print("\n[VRP_HAR] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

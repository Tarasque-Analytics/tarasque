"""
vrp_long_horizon_test.py -- Long-horizon (h=21/63/126) head-to-head: our ML
                            ensemble vs vanilla HAR-RV, on forecast accuracy AND
                            on premium isolation.

Standard claim: HAR-RV's predictive R^2 collapses (often negative) at h>=63 BD
because daily/weekly/monthly trailing RV becomes uninformative against forward
vol that has mean-reverted. Our ensemble has features HAR doesn't (IV term
structure via term_structure_slope, macro, event calendars, GARCH component),
so it should hold up.

We pair IV at the matching calendar horizon:
    h=21 BD  ~ IV_30d
    h=63 BD  ~ IV_91d
    h=126 BD ~ IV_182d
(vsurfd has ATM IV at days=30/60/91/182.)

For each horizon:
  - Walk-forward HAR per ticker (vanilla 1/5/21-day trailing RV features, purge=h)
  - Compare RMSE, MAE, bias, OOS R^2 of ensemble vs HAR
  - Premium decomposition: model premium share = mean(IV - y_true) / mean(IV - y_pred)
    computed for both ensemble and HAR

Output: results/validation/vrp_long_horizon_*.csv
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
from .vrp_har_baseline_compare import daily_gk_rv, har_walk_forward

OUT_DIR = RESULTS_DIR / "validation"
HORIZONS = [21, 63, 126]
HORIZON_TO_IV_DAYS = {21: 30, 63: 91, 126: 182}


def load_iv_term() -> pd.DataFrame:
    """ATM IV at days in {30,91,182}, wide format (ticker, date, iv_30d, iv_91d, iv_182d)."""
    dc, _, _ = load_config()
    print("[VRP_LH] Loading vsurfd (filtering to ATM, days in {30,91,182})...")
    vs = ParquetStore(dc.base_dir).load("vsurfd")
    vs = vs[(vs["delta"] == 50.0) & (vs["days"].isin([30.0, 91.0, 182.0]))]
    vs = vs.copy()
    vs["date"] = pd.to_datetime(vs["date"], format="mixed")
    vs = vs.drop_duplicates(["ticker", "date", "days"])
    wide = vs.pivot_table(index=["ticker", "date"], columns="days",
                          values="impl_volatility", aggfunc="first")
    wide.columns = [f"iv_{int(d)}d" for d in wide.columns]
    print(f"  IV-term wide: {len(wide):,} (ticker,date) pairs")
    return wide.reset_index()


def build_panel_h(h: int) -> pd.DataFrame:
    """Per-ticker predictions filtered to horizon h."""
    rows = []
    for f in sorted(RESULTS_DIR.glob("predictions_*.csv")):
        ticker = f.stem.replace("predictions_", "")
        try:
            df = pd.read_csv(f, parse_dates=["date"],
                             usecols=["date", "y_true", "y_pred", "horizon"])
        except Exception:
            continue
        d = df[df["horizon"] == h].drop(columns=["horizon"]).sort_values("date")
        if len(d) < 60:
            continue
        d["ticker"] = ticker
        rows.append(d)
    return pd.concat(rows, ignore_index=True)


def oos_r2(y: np.ndarray, p: np.ndarray) -> float:
    m = np.isfinite(y) & np.isfinite(p)
    if m.sum() < 10:
        return np.nan
    y, p = y[m], p[m]
    sst = float(np.sum((y - y.mean()) ** 2))
    sse = float(np.sum((y - p) ** 2))
    return 1.0 - sse / sst if sst > 0 else np.nan


def stats_block(y: np.ndarray, p: np.ndarray) -> dict:
    bias = (y - p).mean()
    rmse = float(np.sqrt(((y - p) ** 2).mean()))
    mae = float(np.abs(y - p).mean())
    r2 = oos_r2(y, p)
    return {"bias": float(bias), "rmse": rmse, "mae": mae, "r2": r2}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    iv_term = load_iv_term()

    print("[VRP_LH] Computing daily GK RV per ticker (HAR features)...")
    dc, _, _ = load_config()
    oh = ParquetStore(dc.base_dir).load("ohlcv")
    oh["date"] = pd.to_datetime(oh["date"], format="mixed")
    rv_panel = {tk: daily_gk_rv(
                    g.sort_values("date").set_index("date")[["askhi","bidlo","prc","openprc"]])
                for tk, g in oh.drop_duplicates(["date","ticker"]).groupby("ticker", observed=True)}

    summary_rows = []
    perdh_rows = []
    for h in HORIZONS:
        print(f"\n[VRP_LH] === HORIZON h={h} BD ===")
        panel = build_panel_h(h)
        panel = panel.dropna(subset=["y_true", "y_pred"])
        print(f"  ensemble panel: {len(panel):,} rows, {panel['ticker'].nunique()} tickers")

        # HAR walk-forward per ticker with purge=h
        har_rows = []
        for tk, sub in panel.groupby("ticker"):
            if tk not in rv_panel:
                continue
            y_true_s = sub.set_index("date")["y_true"].sort_index()
            preds = har_walk_forward(rv_panel[tk], y_true_s,
                                      retrain_step=21, min_train=252, purge=h)
            for d, v in preds.dropna().items():
                har_rows.append({"ticker": tk, "date": d, "y_pred_har": float(v)})
        har_df = pd.DataFrame(har_rows)

        # Merge IV at matched horizon
        iv_col = f"iv_{HORIZON_TO_IV_DAYS[h]}d"
        pp = panel.merge(iv_term[["ticker","date", iv_col]].rename(columns={iv_col: "iv"}),
                         on=["ticker","date"], how="inner")
        pp = pp.merge(har_df, on=["ticker","date"], how="inner")
        pp = pp.dropna(subset=["iv","y_true","y_pred","y_pred_har"])
        print(f"  joined w/ IV ({iv_col}) + HAR: {len(pp):,} rows, "
              f"{pp['ticker'].nunique()} tickers")
        if len(pp) < 100:
            print("  -> too few obs, skipping"); continue

        # forecast quality
        ens = stats_block(pp["y_true"].to_numpy(), pp["y_pred"].to_numpy())
        har = stats_block(pp["y_true"].to_numpy(), pp["y_pred_har"].to_numpy())
        print(f"\n  FORECAST QUALITY at h={h}:")
        print(f"    metric    ensemble      HAR        ens-vs-HAR")
        print(f"    bias      {ens['bias']:+.4f}     {har['bias']:+.4f}     "
              f"{'less' if abs(ens['bias']) < abs(har['bias']) else 'more'} biased")
        print(f"    RMSE      {ens['rmse']:.4f}     {har['rmse']:.4f}     "
              f"ens {'+' if ens['rmse']<har['rmse'] else '-'}"
              f"{abs(har['rmse']-ens['rmse'])/har['rmse']*100:.1f}%")
        print(f"    MAE       {ens['mae']:.4f}     {har['mae']:.4f}     "
              f"ens {'+' if ens['mae']<har['mae'] else '-'}"
              f"{abs(har['mae']-ens['mae'])/har['mae']*100:.1f}%")
        print(f"    OOS R^2   {ens['r2']:+.3f}      {har['r2']:+.3f}     "
              f"{'WIN' if ens['r2'] > har['r2'] else 'LOSE'} by {ens['r2']-har['r2']:+.3f}")

        # premium decomposition
        pp["model_prem_ens"] = pp["iv"] - pp["y_pred"]
        pp["model_prem_har"] = pp["iv"] - pp["y_pred_har"]
        pp["expost_prem"]    = pp["iv"] - pp["y_true"]
        m_exp = float(pp["expost_prem"].mean())
        m_ens = float(pp["model_prem_ens"].mean())
        m_har = float(pp["model_prem_har"].mean())
        s_ens = m_exp / m_ens if m_ens != 0 else np.nan
        s_har = m_exp / m_har if m_har != 0 else np.nan
        v_exp = float(pp["expost_prem"].var())
        v_ens = float(pp["model_prem_ens"].var())
        v_har = float(pp["model_prem_har"].var())
        print(f"\n  PREMIUM DECOMP at h={h}  (IV={iv_col}):")
        print(f"    mean ex-post premium (IV - y_true)          : {m_exp:+.4f} (TRUE)")
        print(f"    mean model premium ENSEMBLE (IV - y_pred)   : {m_ens:+.4f}  -> share {s_ens:.0%}")
        print(f"    mean model premium HAR      (IV - y_pred_HAR): {m_har:+.4f}  -> share {s_har:.0%}")
        print(f"    var ratio (ex-post/displayed) ENS {v_exp/v_ens:.0%}  HAR {v_exp/v_har:.0%}")

        summary_rows.append({"horizon": h, "n_obs": len(pp), "n_tickers": pp["ticker"].nunique(),
                             "ens_bias": ens["bias"], "ens_rmse": ens["rmse"],
                             "ens_mae": ens["mae"], "ens_r2": ens["r2"],
                             "har_bias": har["bias"], "har_rmse": har["rmse"],
                             "har_mae": har["mae"], "har_r2": har["r2"],
                             "true_premium": m_exp, "ens_share": s_ens, "har_share": s_har})

    sm = pd.DataFrame(summary_rows)
    print("\n" + "=" * 88)
    print(" SUMMARY ACROSS HORIZONS")
    print("=" * 88)
    cols = ["horizon", "n_obs", "n_tickers", "ens_r2", "har_r2", "ens_mae", "har_mae",
            "true_premium", "ens_share", "har_share"]
    with pd.option_context("display.width", 200, "display.float_format", lambda v: f"{v:+.4f}"):
        print(sm[cols].to_string(index=False))
    sm.to_csv(OUT_DIR / "vrp_long_horizon_summary.csv", index=False)
    print("\n[VRP_LH] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

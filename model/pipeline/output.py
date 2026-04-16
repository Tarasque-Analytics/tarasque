"""
output.py — Standardized JSON output for frontend consumption.

Produces two output types aligned with the frontend mockups:
  1. Per-ticker payloads  ({TICKER}_Payload.json)  — ticker detail page
  2. Market overview       (market_overview.json)   — macro landing page
  3. Metrics summary       (metrics_summary.json)   — internal monitoring
"""
import json
import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .config import DataConfig, ModelConfig, BacktestConfig, SECTOR_ETF_MAP


# GICS code → human-readable sector name
GICS_SECTOR_NAMES: Dict[str, str] = {
    "10": "Energy",
    "15": "Materials",
    "20": "Industrials",
    "25": "Consumer Discretionary",
    "30": "Consumer Staples",
    "35": "Health Care",
    "40": "Financials",
    "45": "Information Technology",
    "50": "Communication Services",
    "55": "Utilities",
    "60": "Real Estate",
}


def _json_safe(obj):
    """Convert numpy/pandas types to JSON-serializable Python types."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    if isinstance(obj, (pd.Timestamp, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, (datetime.date,)):
        return obj.isoformat()
    if pd.isna(obj):
        return None
    raise TypeError(f"Not JSON serializable: {type(obj)}")


def _classify_regime(avg_vol_zscore: float) -> str:
    """Map average vol regime z-score to a human-readable label."""
    if avg_vol_zscore > 1.5:
        return "High Volatility"
    elif avg_vol_zscore > 0.5:
        return "Elevated Uncertainty"
    elif avg_vol_zscore > -0.5:
        return "Relative Certainty Neutral"
    elif avg_vol_zscore > -1.5:
        return "Low Volatility"
    else:
        return "Compressed Volatility"


def _classify_risk_tier(forecast_rv: float, vrp_wedge: float) -> str:
    """Classify ticker risk tier based on forecast vol and VRP."""
    if forecast_rv > 0.35 or vrp_wedge > 0.10:
        return "high"
    elif forecast_rv > 0.20 or vrp_wedge > 0.05:
        return "elevated"
    elif forecast_rv > 0.12:
        return "moderate"
    else:
        return "low"


# ═══════════════════════════════════════════════════════════════════════════
# PER-TICKER PAYLOAD
# ═══════════════════════════════════════════════════════════════════════════

def write_ticker_payload(
    ticker: str,
    predictions: Dict[int, pd.DataFrame],
    feature_df: pd.DataFrame,
    metrics: Dict[int, Dict[str, float]],
    weights: Dict[int, Dict[str, float]],
    sector_code: Optional[str],
    output_dir: Path,
):
    """
    Write {TICKER}_Payload.json for the ticker detail page.

    Parameters
    ----------
    predictions : {horizon: DataFrame with columns [date, y_true, y_pred]}
    feature_df  : Full feature DataFrame for this ticker (index=date)
    metrics     : {horizon: {rmse, mz_alpha, mz_beta, mz_r2, qlike, ...}}
    weights     : {horizon: {XGB: w, RF: w, LassoCV: w}}
    sector_code : GICS sector code (e.g. "10" for Energy), or None
    output_dir  : Directory to write the payload into
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    sector_name = GICS_SECTOR_NAMES.get(str(sector_code), "Unknown") if sector_code else "Unknown"

    # ── Extract latest-date values from feature_df ──
    last_row = feature_df.iloc[-1]
    forecast_rv = {}
    for h, pred_df in predictions.items():
        if len(pred_df) > 0:
            forecast_rv[str(h)] = float(pred_df["y_pred"].iloc[-1])

    def _safe_float(val, default=0.0):
        """Convert to float, returning default for NaN/None."""
        if val is None or pd.isna(val):
            return default
        return float(val)

    garch_21d = _safe_float(last_row.get("rv_21d", 0))
    iv_atm = _safe_float(last_row.get("iv_atm_30d"), None) if "iv_atm_30d" in feature_df.columns else None
    vrp_wedge = _safe_float(last_row.get("vrp_wedge"), None) if "vrp_wedge" in feature_df.columns else None
    vol_zscore = _safe_float(last_row.get("vol_regime_zscore", 0)) if "vol_regime_zscore" in feature_df.columns else 0.0

    # VRP percentile vs trailing 252d
    vrp_pct_1y = None
    if "vrp_wedge" in feature_df.columns:
        vrp_series = feature_df["vrp_wedge"].dropna()
        if len(vrp_series) >= 252:
            trailing = vrp_series.iloc[-252:]
            current = vrp_series.iloc[-1]
            vrp_pct_1y = float((trailing < current).mean())

    # Ensemble weights per horizon (e.g. {"H21": {...}, "H63": {...}, "H126": {...}})
    ens_weights = {
        f"H{h}": w for h, w in sorted(weights.items())
    }

    # Risk tier
    rv_21_forecast = forecast_rv.get("21", garch_21d)
    risk_tier = _classify_risk_tier(rv_21_forecast, vrp_wedge or 0)

    # ── Vol forecast time series ──
    vol_series = {"dates": []}
    for h in sorted(predictions.keys()):
        vol_series[f"predicted_rv_{h}d"] = []

    # Realized and implied series from features
    rv_col = feature_df["rv_21d"] if "rv_21d" in feature_df.columns else pd.Series(dtype=float)
    iv_col = feature_df["iv_atm_30d"] if "iv_atm_30d" in feature_df.columns else pd.Series(dtype=float)

    # Build from the H=21 predictions (most frequent), align other horizons
    if 21 in predictions and len(predictions[21]) > 0:
        base_dates = predictions[21]["date"].tolist()
        vol_series["dates"] = [str(d)[:10] for d in base_dates]
        vol_series["predicted_rv_21d"] = predictions[21]["y_pred"].tolist()
        vol_series["realized_rv_21d"] = predictions[21]["y_true"].tolist()

        # IV at prediction dates
        iv_vals = []
        for d in base_dates:
            if d in iv_col.index:
                iv_vals.append(float(iv_col.loc[d]) if pd.notna(iv_col.loc[d]) else None)
            else:
                iv_vals.append(None)
        vol_series["implied_vol_30d"] = iv_vals

        # Other horizons — align to base dates where available
        for h in sorted(predictions.keys()):
            if h == 21:
                continue
            h_preds = predictions[h].set_index("date")
            vals = []
            for d in base_dates:
                if d in h_preds.index:
                    vals.append(float(h_preds.loc[d, "y_pred"]))
                else:
                    vals.append(None)
            vol_series[f"predicted_rv_{h}d"] = vals

    # ── Calibration data (H=21 primary) ──
    calibration = {}
    cal_h = 21 if 21 in predictions else (min(predictions.keys()) if predictions else None)
    if cal_h and cal_h in predictions and len(predictions[cal_h]) > 0:
        pred_df = predictions[cal_h]
        calibration = {
            "y_true": pred_df["y_true"].tolist(),
            "y_pred": pred_df["y_pred"].tolist(),
        }
        if cal_h in metrics:
            calibration.update({
                "mz_alpha": metrics[cal_h].get("mz_alpha"),
                "mz_beta": metrics[cal_h].get("mz_beta"),
                "mz_r2": metrics[cal_h].get("mz_r2"),
                "rmse": metrics[cal_h].get("rmse"),
                "qlike": metrics[cal_h].get("qlike"),
            })

    # ── Regime label ──
    vol_regime = _classify_regime(vol_zscore)

    payload = {
        "meta": {
            "ticker": ticker,
            "sector": sector_name,
            "gics_code": str(sector_code) if sector_code else None,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "forecast_rv": forecast_rv,
            "garch_21d": garch_21d,
            "market_iv_atm": iv_atm,
            "vrp_wedge": vrp_wedge,
            "vrp_percentile_1y": vrp_pct_1y,
            "vol_regime": vol_regime,
            "risk_tier": risk_tier,
            "z_score_stabilized": vol_zscore,
            "ensemble_weights": ens_weights,
        },
        "vol_forecast_series": vol_series,
        "calibration": calibration,
    }

    path = output_dir / f"{ticker}_Payload.json"
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=_json_safe)

    print(f"[OUTPUT] Wrote {path}")


# ═══════════════════════════════════════════════════════════════════════════
# MARKET OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════

def write_market_overview(
    ticker_payloads: Dict[str, dict],
    all_predictions: Dict[str, Dict[int, pd.DataFrame]],
    sector_map: Dict[str, str],
    output_dir: Path,
):
    """
    Write market_overview.json for the macro landing page.

    Parameters
    ----------
    ticker_payloads : {ticker: payload_dict} — already-built per-ticker payloads
    all_predictions : {ticker: {horizon: pred_df}} — raw prediction DataFrames
    sector_map      : {ticker: gics_code}
    output_dir      : Directory to write into
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Aggregate by sector ──
    sector_data: Dict[str, list] = {}
    for ticker, payload in ticker_payloads.items():
        gics = payload["meta"].get("gics_code") or sector_map.get(ticker, "Unknown")
        if gics not in sector_data:
            sector_data[gics] = []
        sector_data[gics].append(payload)

    sector_risk = []
    for gics_code, payloads in sorted(sector_data.items()):
        tickers_in_sector = [p["meta"]["ticker"] for p in payloads]
        vrp_values = [p["meta"]["vrp_wedge"] for p in payloads if p["meta"]["vrp_wedge"] is not None]
        rv_values = [p["meta"]["forecast_rv"].get("21", 0) for p in payloads]
        pct_values = [p["meta"]["vrp_percentile_1y"] for p in payloads if p["meta"]["vrp_percentile_1y"] is not None]

        sector_risk.append({
            "sector": GICS_SECTOR_NAMES.get(str(gics_code), "Unknown"),
            "gics_code": str(gics_code),
            "avg_vrp_wedge": float(np.mean(vrp_values)) if vrp_values else None,
            "avg_forecast_rv_21d": float(np.mean(rv_values)) if rv_values else None,
            "percentile_1y": float(np.mean(pct_values)) if pct_values else None,
            "tickers": tickers_in_sector,
        })

    # Sort by avg forecast RV descending for risk ranking
    sector_risk.sort(key=lambda s: s["avg_forecast_rv_21d"] or 0, reverse=True)

    highest_risk = sector_risk[0] if sector_risk else None
    lowest_risk = sector_risk[-1] if sector_risk else None

    # ── Treemap data ──
    treemap = []
    for ticker, payload in ticker_payloads.items():
        meta = payload["meta"]
        rv_21 = meta["forecast_rv"].get("21", 0)
        vrp = meta["vrp_wedge"] or 0
        # Risk score: weighted combination of forecast vol and VRP
        risk_score = rv_21 * 0.7 + abs(vrp) * 0.3
        treemap.append({
            "ticker": ticker,
            "sector": meta["sector"],
            "gics_code": meta.get("gics_code"),
            "risk_score": float(risk_score),
            "vrp_wedge": meta["vrp_wedge"],
            "forecast_rv_21d": rv_21,
        })
    treemap.sort(key=lambda t: t["risk_score"], reverse=True)

    # ── GARCH calibration (aggregate) ──
    all_y_true = []
    all_y_pred = []
    for ticker, horizons in all_predictions.items():
        if 21 in horizons and len(horizons[21]) > 0:
            all_y_true.extend(horizons[21]["y_true"].tolist())
            all_y_pred.extend(horizons[21]["y_pred"].tolist())

    calibration = {}
    if all_y_true:
        from sklearn.linear_model import LinearRegression
        yt = np.array(all_y_true)
        yp = np.array(all_y_pred)
        lr = LinearRegression()
        lr.fit(yp.reshape(-1, 1), yt)
        calibration = {
            "all_y_true": all_y_true,
            "all_y_pred": all_y_pred,
            "overall_r2": float(lr.score(yp.reshape(-1, 1), yt)),
            "overall_mz_beta": float(lr.coef_[0]),
        }

    # ── Regime (average z-score across all tickers) ──
    z_scores = [p["meta"]["z_score_stabilized"] for p in ticker_payloads.values()
                if p["meta"]["z_score_stabilized"] is not None]
    avg_zscore = float(np.mean(z_scores)) if z_scores else 0.0
    rv_values_all = [p["meta"]["forecast_rv"].get("21", 0) for p in ticker_payloads.values()]
    avg_market_vol = float(np.mean(rv_values_all)) if rv_values_all else 0.0

    # ── Sector risk history (from H=21 predictions) ──
    sector_risk_history = _build_sector_risk_history(all_predictions, sector_map)

    overview = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "regime": {
            "label": _classify_regime(avg_zscore),
            "vol_regime_zscore": avg_zscore,
            "market_vol_21d": avg_market_vol,
        },
        "sector_risk": sector_risk,
        "highest_risk_sector": {
            "sector": highest_risk["sector"],
            "gics_code": highest_risk["gics_code"],
        } if highest_risk else None,
        "lowest_risk_sector": {
            "sector": lowest_risk["sector"],
            "gics_code": lowest_risk["gics_code"],
        } if lowest_risk else None,
        "treemap": treemap,
        "garch_calibration": calibration,
        "sector_risk_history": sector_risk_history,
    }

    path = output_dir / "market_overview.json"
    with open(path, "w") as f:
        json.dump(overview, f, indent=2, default=_json_safe)

    print(f"[OUTPUT] Wrote {path}")


def _build_sector_risk_history(
    all_predictions: Dict[str, Dict[int, pd.DataFrame]],
    sector_map: Dict[str, str],
) -> dict:
    """
    Build time series of average predicted vol by sector (H=21).

    Returns {dates: [...], "Energy": [...], "Tech": [...], ...}
    """
    # Group tickers by sector
    sector_tickers: Dict[str, list] = {}
    for ticker, gics in sector_map.items():
        name = GICS_SECTOR_NAMES.get(str(gics), "Unknown")
        if name not in sector_tickers:
            sector_tickers[name] = []
        sector_tickers[name].append(ticker)

    # Build per-sector average predicted vol over time
    sector_series: Dict[str, pd.Series] = {}
    for sector_name, tickers in sector_tickers.items():
        frames = []
        for t in tickers:
            if t in all_predictions and 21 in all_predictions[t]:
                df = all_predictions[t][21]
                if len(df) > 0:
                    s = df.set_index("date")["y_pred"]
                    s.name = t
                    frames.append(s)
        if frames:
            combined = pd.concat(frames, axis=1)
            sector_series[sector_name] = combined.mean(axis=1)

    if not sector_series:
        return {"dates": []}

    # Align all sectors to a common date index
    all_dates = sorted(set().union(*(s.index for s in sector_series.values())))
    result = {"dates": [str(d)[:10] for d in all_dates]}

    for sector_name, series in sector_series.items():
        aligned = series.reindex(all_dates)
        result[sector_name] = [float(v) if pd.notna(v) else None for v in aligned.values]

    return result


# ═══════════════════════════════════════════════════════════════════════════
# METRICS SUMMARY
# ═══════════════════════════════════════════════════════════════════════════

def write_metrics_summary(
    all_metrics: List[dict],
    output_dir: Path,
):
    """Write metrics_summary.json for internal model monitoring."""
    output_dir.mkdir(parents=True, exist_ok=True)

    path = output_dir / "metrics_summary.json"
    with open(path, "w") as f:
        json.dump(all_metrics, f, indent=2, default=_json_safe)

    print(f"[OUTPUT] Wrote {path}")

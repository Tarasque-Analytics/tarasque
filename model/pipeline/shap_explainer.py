"""
shap_explainer.py — Daily SHAP computation for the live forecast layer.

SHAP is computed ONLY for concurrent (forecast) runs, never for backtest
predictions. Backtest rows have many WFA refits per ticker — there's no
single trained model to explain. The daily forecast has exactly one
persisted ensemble per ticker, so SHAP is well-defined.

Architecture:
  - daily_forecast.py calls compute_ensemble_shap_top_k() with today's feature
    row + the loaded ensemble joblib.
  - Returns a dict matching SUPABASE_SCHEMA.md §2 SHAP blob spec.
  - daily_forecast.py serialises to JSON and writes to
    forecasts/<TICKER>_shap.csv (parallel to predictions_<TICKER>.csv).
  - export_for_webapp.py merges SHAP into the per-ticker webapp bundle
    where present, leaves NULL elsewhere (i.e. backtest history).

Ensemble SHAP methodology:
  The user-facing prediction is the ensemble blend (XGB + RF + ElasticNet)
  weighted by inverse-validation-RMSE. For SHAP to faithfully decompose
  THAT prediction, we explain each sub-model separately and combine:

      shap_ensemble[i, f] = Σ_m  weight[m] · shap_m[i, f]
      base_ensemble[i]    = Σ_m  weight[m] · base_m[i]

  - XGB: shap.TreeExplainer (exact for tree models)
  - RF:  shap.TreeExplainer (exact for forests via TreeSHAP)
  - ElasticNet (linear): shap = coef * (x_scaled − μ_scaled); base = intercept

  The combined SHAP sums (over features) to (prediction − base), matching
  the ensemble's actual output.

Display names:
  Internal feature names (e.g. inflation_forward_5y5y) → user-facing
  display names (e.g. "Inflation (5y5y fwd)") via FEATURE_DISPLAY_NAMES.
  This is the relational mapping the frontend reads off the JSON blob.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# Feature display-name mapping
# ─────────────────────────────────────────────────────────────────────────────
# Internal name → user-facing label. Frontend reads `display` off the JSON
# blob; this mapping is the single source of truth for "what does this
# feature mean in human-readable terms?"
#
# Style choices:
#   - "Inflation (5y5y fwd)" — specific over ambiguous "Inflation"
#   - "10Y Treasury yield" — specific over ambiguous "yield"
#   - Parenthetical units / windows where they clarify
#   - Short enough to fit in a 200px-wide SHAP waterfall row

FEATURE_DISPLAY_NAMES: Dict[str, str] = {
    # ── Realised vol ladder ────────────────────────────────────────────────
    'rv_5d':                            'Realized vol (5d)',
    'rv_10d':                           'Realized vol (10d)',
    'rv_21d':                           'Realized vol (21d)',
    'rv_63d':                           'Realized vol (63d)',
    'rv_126d':                          'Realized vol (126d)',
    'ewma_vol':                         'EWMA vol',
    'ret_TARGET':                       'Realized return (target window)',

    # ── Vol dynamics ───────────────────────────────────────────────────────
    'vol_trend':                        'Vol trend',
    'vol_vel':                          'Vol velocity',
    'vol_of_vol':                       'Vol of vol',
    'vol_regime_zscore':                'Vol regime z-score',
    'vol_chg_21d':                      'Vol change (21d)',

    # ── GARCH ──────────────────────────────────────────────────────────────
    'garch_cond_vol':                   'GARCH conditional vol',

    # ── Technicals ─────────────────────────────────────────────────────────
    'tech_RSI':                         'RSI',
    'tech_ATR':                         'ATR',
    'tech_MACD_hist':                   'MACD histogram',

    # ── Options surface ────────────────────────────────────────────────────
    'iv_atm_30d':                       'ATM IV (30d)',
    'put_call_skew_30d':                'Put-call skew (30d)',
    'put_call_abs_skew_30d':            'Skew magnitude (30d)',
    'term_structure_slope':             'IV term-structure slope',
    'vrp_wedge':                        'VRP wedge (IV − RV)',
    'iv_atm_z_score':                   'IV Z-score',

    # ── Open interest (25-delta) ───────────────────────────────────────────
    'oi_put_call_ratio_25d':            'Put-call OI ratio (25Δ)',
    'fear_intensity_25d':               'Fear intensity (25Δ)',
    'oi_hedge_pressure_chg_5d':         'Hedge-pressure change (5d)',

    # ── Event proximity gravities ──────────────────────────────────────────
    'event_fed_gravity':                'FOMC proximity',
    'event_earn_gravity':               'Earnings proximity',
    'event_div_gravity':                'Dividend proximity',
    'event_cpi_gravity':                'CPI release proximity',
    'event_nfp_gravity':                'NFP release proximity',

    # ── Macro (rates / credit / fx / inflation) ────────────────────────────
    'treasury_10y':                     '10Y Treasury yield',
    'treasury_3mo':                     '3M Treasury yield',
    'hy_spread':                        'HY credit spread',
    'breakeven_5y':                     '5Y breakeven inflation',
    'dollar_index':                     'Dollar index (DXY)',
    'inflation_forward_5y5y':           'Inflation (5y5y fwd)',
    'macro_yield_curve_slope':          'Yield curve slope (10y − 3m)',
    'macro_hy_spread':                  'HY credit spread',
    'macro_hy_spread_chg_5d':           'HY spread change (5d)',
    'macro_breakeven_5y':               '5Y breakeven inflation',
    'macro_inflation_fwd_5y5y':         'Inflation (5y5y fwd)',
    'macro_inflation_fwd_chg_21d':      'Inflation change (21d)',
    'macro_inflation_fwd_abs_chg_21d':  'Inflation move magnitude (21d)',
    'macro_inflation_fwd_chg_63d':      'Inflation change (63d)',
    'macro_inflation_fwd_zscore':       'Inflation z-score',
    'macro_dollar_ret':                 'Dollar return',

    # ── Factor ETF returns + momentum ──────────────────────────────────────
    'ret_SPY':                          'SPY return',
    'ret_VIXY':                         'VIXY return',
    'ret_HYG':                          'HYG return',
    'ret_USO':                          'USO return',
    'ret_TLT':                          'TLT return',
    'ret_UUP':                          'UUP return',
    'mom21_SPY':                        'SPY momentum (21d)',
    'mom21_VIXY':                       'VIXY momentum (21d)',
    'mom21_HYG':                        'HYG momentum (21d)',
    'mom21_USO':                        'USO momentum (21d)',
    'mom21_TLT':                        'TLT momentum (21d)',
    'mom21_UUP':                        'UUP momentum (21d)',

    # ── Cross-sectional / residual / sector ────────────────────────────────
    'beta_spy':                         'SPY beta',
    'res_vol':                          'Residual vol',
    'res_vol_vel':                      'Residual vol velocity',
    'price_regime':                     'Price regime',
    'corr_sector_21d':                  'Sector correlation (21d)',
    'corr_sector_252d':                 'Sector correlation (252d)',
    'sector_wedge':                     'Sector VRP wedge',
}


def display_name(feature: str) -> str:
    """Return user-facing label for an internal feature name; fall back to
    the internal name if unmapped."""
    return FEATURE_DISPLAY_NAMES.get(feature, feature)


# ─────────────────────────────────────────────────────────────────────────────
# Ensemble SHAP
# ─────────────────────────────────────────────────────────────────────────────

def _shap_xgb(model, X_scaled: np.ndarray,
              feature_names: Optional[list] = None) -> tuple[np.ndarray, float]:
    """SHAP for an XGBoost regressor via XGBoost's native pred_contribs.

    Uses model.get_booster().predict(DMatrix, pred_contribs=True) — works on
    both CPU- and CUDA-trained models, much faster than shap.TreeExplainer
    on CUDA boosters (which can hang due to GPU/CPU device juggling).

    XGBoost requires DMatrix feature_names to match those used at training
    time — pass `feature_names` from the model's predictor list.

    Returns:
      shap_values shape (n_features,), base value (scalar).
    """
    import xgboost as xgb
    booster = model.get_booster()
    # Force CPU on the booster for SHAP — CUDA boosters can hang on
    # pred_contribs during the GPU/CPU round-trip with a single sample.
    # SHAP is single-row work, no GPU benefit.
    booster.set_param({'device': 'cpu'})
    dmat = xgb.DMatrix(X_scaled, feature_names=feature_names)
    contribs = booster.predict(dmat, pred_contribs=True)
    # Shape: (n_samples, n_features + 1) — last col is the bias / base value
    if contribs.ndim == 1:
        contribs = contribs.reshape(1, -1)
    shap_values = contribs[0, :-1]
    base = float(contribs[0, -1])
    return shap_values, base


def _shap_rf(model, X_scaled: np.ndarray) -> tuple[np.ndarray, float]:
    """SHAP for a RandomForestRegressor via TreeExplainer.

    RF SHAP with check_additivity can fail if there's any float-precision
    mismatch; we disable that check since the ensemble combination doesn't
    require per-model additivity.
    """
    import shap
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_scaled, check_additivity=False)
    if shap_values.ndim == 2:
        shap_values = shap_values[0]
    # expected_value can be a scalar OR a 1-element array depending on shap version
    ev = explainer.expected_value
    if hasattr(ev, '__len__'):
        ev = ev[0] if len(ev) > 0 else 0.0
    base = float(ev)
    return shap_values, base


def _shap_linear(model, X_scaled: np.ndarray, scaler_mean: np.ndarray) -> tuple[np.ndarray, float]:
    """Exact SHAP for a linear regressor (ElasticNetCV).

    For a linear model y = β·x + α with feature mean μ over the training set:
        shap_i = β_i · (x_i − μ_i)
        base   = α + β·μ      (= model.predict(μ); the expected value)
        prediction = base + Σ_i shap_i = α + β·x  ✓

    For an already-scaled X (mean ~0, std ~1), μ_i ≈ 0, so shap_i ≈ β_i · x_i.
    We pass `scaler_mean` explicitly so that if a custom centring is used it
    still works. For a standard StandardScaler-transformed input, the mean
    is the zero vector.
    """
    coefs = np.asarray(model.coef_, dtype=float).flatten()
    intercept = float(model.intercept_)
    x = X_scaled[0] if X_scaled.ndim == 2 else X_scaled
    shap_values = coefs * (x - scaler_mean)
    base = intercept + float(coefs @ scaler_mean)
    return shap_values, base


def compute_ensemble_shap(
    ensemble: Dict[str, Any],
    weights: Dict[str, float],
    X_raw_row: pd.Series,
    final_scaler,
    predictors: List[str],
) -> tuple[np.ndarray, float, float]:
    """Compute the ensemble SHAP for one row.

    Inputs
    ------
    ensemble       : dict like {'XGB': xgb_model, 'RF': rf_model, 'ElasticNet': en_model}
    weights        : dict like {'XGB': w_xgb, 'RF': w_rf, 'ElasticNet': w_en}
    X_raw_row      : pandas Series with the raw (un-scaled) feature row
    final_scaler   : the fitted StandardScaler from the joblib
    predictors     : ordered list of feature names matching what the model was trained on

    Returns
    -------
    (shap_values, base_value, predicted_value) — all in the model's target
    space (log-vol). The SHAP values sum to (predicted − base) by construction.
    """
    # Align the raw row to the predictor order; fill any missing with 0
    # (matches the predictor-alignment logic in run.py's forecast mode).
    x_raw = np.asarray(
        [float(X_raw_row.get(p, 0.0) if pd.notna(X_raw_row.get(p, 0.0)) else 0.0)
         for p in predictors], dtype=float
    ).reshape(1, -1)
    x_scaled = final_scaler.transform(x_raw)

    # Per-model SHAP
    shap_xgb, base_xgb = _shap_xgb(ensemble['XGB'], x_scaled, feature_names=predictors)
    shap_rf,  base_rf  = _shap_rf(ensemble['RF'], x_scaled)
    # StandardScaler centring vector: the model was trained on x_scaled
    # where (x − scaler.mean_) / scaler.scale_, so the scaled-space mean is 0
    scaled_mean = np.zeros(len(predictors), dtype=float)
    shap_en, base_en = _shap_linear(ensemble['ElasticNet'], x_scaled, scaled_mean)

    # Weighted combination
    w_xgb = float(weights.get('XGB', 0.0))
    w_rf  = float(weights.get('RF', 0.0))
    w_en  = float(weights.get('ElasticNet', 0.0))
    total_w = w_xgb + w_rf + w_en
    if total_w <= 0:
        raise ValueError(f'Ensemble weights sum to {total_w}; check joblib.')
    # Normalise (defensive — usually already sums to 1)
    w_xgb, w_rf, w_en = w_xgb / total_w, w_rf / total_w, w_en / total_w

    shap_ens = w_xgb * shap_xgb + w_rf * shap_rf + w_en * shap_en
    base_ens = w_xgb * base_xgb + w_rf * base_rf + w_en * base_en
    pred_ens = base_ens + float(shap_ens.sum())

    return shap_ens, base_ens, pred_ens


def compute_ensemble_shap_top_k(
    ensemble: Dict[str, Any],
    weights: Dict[str, float],
    X_raw_row: pd.Series,
    final_scaler,
    predictors: List[str],
    k: int = 10,
) -> Dict[str, Any]:
    """Compute ensemble SHAP and return top-K features by |shap|.

    Returns the dict shape spec'd in SUPABASE_SCHEMA.md §2:
      {
        "base_value":      float,
        "predicted_value": float,
        "features": [
          {"name": str, "display": str, "value": float, "shap": float, "abs_shap": float},
          ...
        ]
      }
    """
    shap_values, base, pred = compute_ensemble_shap(
        ensemble, weights, X_raw_row, final_scaler, predictors
    )

    # Pair feature names with shap + raw value
    rows = []
    for i, name in enumerate(predictors):
        raw_v = X_raw_row.get(name, np.nan)
        try:
            raw_v = float(raw_v) if pd.notna(raw_v) else None
        except (TypeError, ValueError):
            raw_v = None
        rows.append({
            'name':     name,
            'display':  display_name(name),
            'value':    raw_v,
            'shap':     float(shap_values[i]),
            'abs_shap': float(abs(shap_values[i])),
        })

    # Top-K by |shap|
    rows.sort(key=lambda r: r['abs_shap'], reverse=True)
    top = rows[:k]

    return {
        'base_value':      round(base, 6),
        'predicted_value': round(pred, 6),
        'features':        top,
    }


def serialize_shap_blob(blob: Dict[str, Any]) -> str:
    """JSON-serialise a SHAP blob for storage in shap_h*_top10 columns.
    Compact separators to keep CSV column width down."""
    return json.dumps(blob, separators=(',', ':'), default=lambda x: None if pd.isna(x) else x)


def parse_shap_blob(json_str: str) -> Dict[str, Any]:
    """Inverse of serialize_shap_blob."""
    return json.loads(json_str)

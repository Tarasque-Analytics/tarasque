"""
premium_curve.py — Forward premium curve math.

The model side stores the 7 anchor points per (ticker, date) in
volatility_history:
  - Model:  (21td, pfv_cal_21), (63td, pfv_cal_63), (126td, pfv_cal_126)   [TRADING days]
  - Market: (30cd, iv_atm_30d), (60cd, iv_atm_60d), (91cd, iv_atm_91d), (182cd, iv_atm_182d)
                                                                            [CALENDAR days]

UNIT CLASH: model is in trading days (annualised via sqrt(252)), market IV
is in calendar days (OptionMetrics, ACT/365). All math here normalises to
a common TRADING-DAY axis via the constant ratio 252/365 ≈ 0.6904. Frontend
plotting should do the same conversion when placing market anchors on the
same chart as model horizons.

  Trading days → calendar days: td × (365/252) ≈ td × 1.448
  Calendar days → trading days: cd × (252/365) ≈ cd × 0.690

Effect on anchor placement (trading-day axis):
  Market 30cd  → 20.71 td (vs Model 21 td)   ← nearly coincident
  Market 60cd  → 41.42 td
  Market 91cd  → 62.79 td (vs Model 63 td)   ← nearly coincident
  Market 182cd → 125.59 td (vs Model 126 td) ← nearly coincident

The ratio is a fixed-constant approximation. Per-row exactness would require
counting NYSE business days between prediction_date and prediction_date+CD,
which fluctuates ±2 days based on holiday positioning. The fixed-ratio error
translates to ~0.3pp on interpolated IV — small relative to model uncertainty.
Calendar-aware per-row conversion is a v2 upgrade.

Frontend splines those 7 points client-side (d3.curveMonotoneX, on the same
trading-day axis after the same 252/365 conversion) to render the two
continuous curves on the equity page Forward Vol Forecast chart.

THIS module computes 5 scalar premiums per row for the equity-page side panel
and for backend cross-ticker SQL queries:
  - fwd_premium_21d       = IV(21td)  − Model(21td)
  - fwd_premium_63d       = IV(63td)  − Model(63td)
  - fwd_premium_126d      = IV(126td) − Model(126td)
  - fwd_premium_21_to_63d  = forward_IV[21,63]  − forward_Model[21,63]
  - fwd_premium_63_to_126d = forward_IV[63,126] − forward_Model[63,126]

All target horizons are in TRADING days (matching the model's native units
and the chart axis labels "21d 63d 126d").

Sign convention: positive = market pricing more fear than the model
(matches the equity-page UI: "Wedge +6.6pp" means the market is 6.6pp above us).

Spline methodology: PCHIP on TOTAL VARIANCE (T × σ²) where T = trading days
/ 252 (in years). Total variance is additive across non-overlapping windows
so forward-window IV is exactly recoverable from PCHIP spline values at the
window boundaries. PCHIP is monotonicity-preserving so the curve doesn't
overshoot at the joins. This is the standard practitioner choice.
"""
from __future__ import annotations

from typing import Mapping, Optional

import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator


TRADING_DAYS_PER_YEAR = 252.0
CALENDAR_DAYS_PER_YEAR = 365.0
CAL_TO_TRADING = TRADING_DAYS_PER_YEAR / CALENDAR_DAYS_PER_YEAR   # ≈ 0.6904
TRADING_TO_CAL = CALENDAR_DAYS_PER_YEAR / TRADING_DAYS_PER_YEAR   # ≈ 1.4484


def _to_years(td: float) -> float:
    """Trading days → years using 252-day convention."""
    return td / TRADING_DAYS_PER_YEAR


def cal_to_trading_days(cal_days: float | np.ndarray) -> float | np.ndarray:
    """Convert calendar DTE → equivalent trading days via the 252/365 ratio."""
    return np.asarray(cal_days) * CAL_TO_TRADING


def trading_to_cal_days(trading_days: float | np.ndarray) -> float | np.ndarray:
    """Convert trading days → equivalent calendar DTE via the 365/252 ratio."""
    return np.asarray(trading_days) * TRADING_TO_CAL


def interp_iv(target_days: float | np.ndarray,
              anchor_days: np.ndarray,
              anchor_ivs: np.ndarray) -> float | np.ndarray:
    """PCHIP-on-total-variance interpolation of IV to target horizon(s).

    Inputs
    ------
    target_days : scalar or 1-D array of target DTE (in trading days)
    anchor_days : 1-D array of anchor DTE (must be strictly increasing)
    anchor_ivs  : 1-D array of annualised IVs at each anchor (decimal,
                  e.g. 0.231 = 23.1%)

    Returns
    -------
    Interpolated IV (annualised decimal) at target_days. Returns NaN at
    target points where the spline can't be built (any NaN in anchors) or
    where the variance math goes negative.
    """
    anchor_days = np.asarray(anchor_days, dtype=float)
    anchor_ivs = np.asarray(anchor_ivs, dtype=float)

    # Require >= 2 finite anchors to spline
    finite = np.isfinite(anchor_days) & np.isfinite(anchor_ivs) & (anchor_days > 0)
    if finite.sum() < 2:
        if np.isscalar(target_days):
            return np.nan
        return np.full_like(np.asarray(target_days, dtype=float), np.nan)

    ad = anchor_days[finite]
    ai = anchor_ivs[finite]

    # Build PCHIP on (years, total_variance)
    t_years = ad / TRADING_DAYS_PER_YEAR
    total_var = t_years * ai ** 2
    spline = PchipInterpolator(t_years, total_var, extrapolate=False)

    # Clip target to anchor range — defensible "best-available" boundary
    # behavior. Avoids PCHIP overshoot from short-side extrapolation when the
    # 21d model horizon is below the lowest market anchor (30d). When Alpaca
    # short-DTE IV gets spliced in, the anchor range will naturally extend
    # below 21d and this clip becomes a no-op.
    target_arr = np.asarray(target_days, dtype=float)
    target_clipped = np.clip(target_arr, t_years.min() * TRADING_DAYS_PER_YEAR,
                             t_years.max() * TRADING_DAYS_PER_YEAR)
    target_years = target_clipped / TRADING_DAYS_PER_YEAR
    interp_var = spline(target_years)
    # Convert back to annualised IV
    with np.errstate(invalid='ignore', divide='ignore'):
        out_iv = np.sqrt(np.where(target_years > 0, interp_var / target_years, np.nan))
    out_iv = np.where(np.isfinite(out_iv) & (interp_var > 0), out_iv, np.nan)
    if np.isscalar(target_days):
        return float(out_iv)
    return out_iv


def forward_iv(t1_days: float, t2_days: float,
               iv_at_t1: float, iv_at_t2: float) -> float:
    """Forward-starting IV for the window [t1_days, t2_days].

    Uses total-variance differencing:
        forward_var = (T2·σ²(T2) − T1·σ²(T1)) / (T2 − T1)
        forward_iv = sqrt(forward_var)
    Returns NaN if forward variance would be negative (calendar arbitrage)
    or any input is NaN.
    """
    if not all(np.isfinite([t1_days, t2_days, iv_at_t1, iv_at_t2])):
        return np.nan
    if t2_days <= t1_days or t1_days <= 0:
        return np.nan
    t1 = _to_years(t1_days)
    t2 = _to_years(t2_days)
    var1 = t1 * iv_at_t1 ** 2
    var2 = t2 * iv_at_t2 ** 2
    fwd_var = (var2 - var1) / (t2 - t1)
    if fwd_var <= 0:
        return np.nan
    return float(np.sqrt(fwd_var))


def compute_premium_scalars(
    pfv_cal_21: float, pfv_cal_63: float, pfv_cal_126: float,
    iv_atm_30d: float, iv_atm_60d: float, iv_atm_91d: float, iv_atm_182d: float,
) -> Mapping[str, float]:
    """Compute the 5 scalar premiums for one (ticker, date) row.

    All target horizons are in TRADING days. The market IV anchors are
    converted from calendar days to trading days via the 252/365 ratio
    before splining, so all math happens on a single trading-day x-axis.

    Sign convention: positive = market pricing more fear than the model.
    Returns dict with keys fwd_premium_21d / 63d / 126d / 21_to_63d / 63_to_126d.
    """
    # Model anchors — already in trading days
    model_days = np.array([21.0, 63.0, 126.0])
    model_ivs  = np.array([pfv_cal_21, pfv_cal_63, pfv_cal_126])

    # Market anchors — convert calendar DTE to equivalent trading days
    market_days_cal = np.array([30.0, 60.0, 91.0, 182.0])
    market_days = cal_to_trading_days(market_days_cal)   # [20.7, 41.4, 62.8, 125.6]
    market_ivs  = np.array([iv_atm_30d, iv_atm_60d, iv_atm_91d, iv_atm_182d])

    # Interpolate market IV to the three model horizons (all in trading days)
    target_days = np.array([21.0, 63.0, 126.0])
    market_at_target = interp_iv(target_days, market_days, market_ivs)
    # Pairwise model IV is already at 21/63/126 — no interp needed
    cumulative_wedge = market_at_target - model_ivs

    # Isolated forward-window premiums [21,63] and [63,126] in trading days
    market_at_21  = market_at_target[0]
    market_at_63  = market_at_target[1]
    market_at_126 = market_at_target[2]

    fwd_iv_market_21_63   = forward_iv(21,  63,  market_at_21,  market_at_63)
    fwd_iv_market_63_126  = forward_iv(63,  126, market_at_63,  market_at_126)
    fwd_iv_model_21_63    = forward_iv(21,  63,  pfv_cal_21,    pfv_cal_63)
    fwd_iv_model_63_126   = forward_iv(63,  126, pfv_cal_63,    pfv_cal_126)

    iso_21_63  = (fwd_iv_market_21_63 - fwd_iv_model_21_63
                  if np.isfinite(fwd_iv_market_21_63) and np.isfinite(fwd_iv_model_21_63)
                  else np.nan)
    iso_63_126 = (fwd_iv_market_63_126 - fwd_iv_model_63_126
                  if np.isfinite(fwd_iv_market_63_126) and np.isfinite(fwd_iv_model_63_126)
                  else np.nan)

    return {
        'fwd_premium_21d':         float(cumulative_wedge[0]) if np.isfinite(cumulative_wedge[0]) else np.nan,
        'fwd_premium_63d':         float(cumulative_wedge[1]) if np.isfinite(cumulative_wedge[1]) else np.nan,
        'fwd_premium_126d':        float(cumulative_wedge[2]) if np.isfinite(cumulative_wedge[2]) else np.nan,
        'fwd_premium_21_to_63d':   float(iso_21_63),
        'fwd_premium_63_to_126d':  float(iso_63_126),
    }


def compute_premium_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Apply compute_premium_scalars across a DataFrame.

    Input must have these columns:
      pfv_cal_21, pfv_cal_63, pfv_cal_126,
      iv_atm_30d, iv_atm_60d, iv_atm_91d, iv_atm_182d

    Returns the same DataFrame with 5 fwd_premium_* columns added (overwrites
    if present).
    """
    required = ['pfv_cal_21', 'pfv_cal_63', 'pfv_cal_126',
                'iv_atm_30d', 'iv_atm_60d', 'iv_atm_91d', 'iv_atm_182d']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f'compute_premium_columns missing inputs: {missing}')

    new_cols = {
        'fwd_premium_21d':        np.full(len(df), np.nan),
        'fwd_premium_63d':        np.full(len(df), np.nan),
        'fwd_premium_126d':       np.full(len(df), np.nan),
        'fwd_premium_21_to_63d':  np.full(len(df), np.nan),
        'fwd_premium_63_to_126d': np.full(len(df), np.nan),
    }

    arr = df[required].to_numpy(dtype=float)
    for i in range(len(df)):
        scalars = compute_premium_scalars(*arr[i])
        for k, v in scalars.items():
            new_cols[k][i] = v

    out = df.copy()
    for k, v in new_cols.items():
        out[k] = v
    return out

"""
utils.py — Shared helpers used across the pipeline.

Ported from volarbmodel_backtest.py: clean_num (:35-42), QuantLib (:517-546),
EventCalendar (:91-97).
"""
import numpy as np
import pandas as pd
from datetime import datetime, date
from scipy.stats import norm
from scipy.optimize import brentq


# ---------------------------------------------------------------------------
# Sanitisation
# ---------------------------------------------------------------------------

def clean_num(val, decimals=2):
    """Sanitize float for JSON serialization. NaN/Inf → None."""
    if val is None or pd.isna(val) or np.isinf(val):
        return None
    return round(float(val), decimals)


# ---------------------------------------------------------------------------
# Black-Scholes
# ---------------------------------------------------------------------------

def bs_price(S, K, T, r, sigma, type_="call"):
    """European option price via Black-Scholes."""
    if T <= 1e-5:
        return max(0, S - K) if type_ == "call" else max(0, K - S)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if type_ == "call":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def implied_vol(S, K, T, r, price, type_="call"):
    """Invert Black-Scholes for implied volatility via Brent's method."""
    intrinsic = max(0, S - K if type_ == "call" else K - S)
    if price <= intrinsic:
        return 0.0
    try:
        return brentq(
            lambda sigma: bs_price(S, K, T, r, sigma, type_) - price,
            1e-4, 5.0, xtol=1e-6,
        )
    except (ValueError, RuntimeError):
        return np.nan


# ---------------------------------------------------------------------------
# Monte Carlo cone  (from volarbmodel_backtest.py:528-546)
# ---------------------------------------------------------------------------

def monte_carlo_cone(S0, sigma, T, rmse_vol, r=0.0359, n_sims=500):
    """
    Generate a price cone via GBM with stochastic vol shocks.

    Returns
    -------
    chart_data : dict   {"p95", "p05", "mean", "steps"}
    tail_risk  : float  5th-percentile terminal price
    """
    steps = max(5, int(T * 252))
    dt = T / steps
    paths = np.zeros((n_sims, steps + 1))
    paths[:, 0] = S0

    for t in range(1, steps + 1):
        shock_vol = np.maximum(0.01, sigma + np.random.normal(0, rmse_vol, n_sims))
        z = np.random.standard_normal(n_sims)
        paths[:, t] = paths[:, t - 1] * np.exp(
            (r - 0.5 * shock_vol ** 2) * dt + shock_vol * np.sqrt(dt) * z
        )

    p95 = np.percentile(paths, 95, axis=0)
    p05 = np.percentile(paths, 5, axis=0)
    mean_path = np.mean(paths, axis=0)

    chart_data = {
        "p95": p95.tolist(),
        "p05": p05.tolist(),
        "mean": mean_path.tolist(),
        "steps": list(range(steps + 1)),
    }
    return chart_data, float(p05[-1])


# ---------------------------------------------------------------------------
# FOMC Calendar  (from volarbmodel_backtest.py:91-97)
# ---------------------------------------------------------------------------

# Extend annually as new dates are announced.
# Historical dates are the announcement/decision day of each FOMC meeting.
# 2026+ dates are scheduled projections — verify as they are confirmed.
FOMC_DATES = sorted([
    datetime.strptime(d, "%Y-%m-%d").date()
    for d in [
        # 2014
        "2014-01-29", "2014-03-19", "2014-04-30", "2014-06-18",
        "2014-07-30", "2014-09-17", "2014-10-29", "2014-12-17",
        # 2015
        "2015-01-28", "2015-03-18", "2015-04-29", "2015-06-17",
        "2015-07-29", "2015-09-17", "2015-10-28", "2015-12-16",
        # 2016
        "2016-01-27", "2016-03-16", "2016-04-27", "2016-06-15",
        "2016-07-27", "2016-09-21", "2016-11-02", "2016-12-14",
        # 2017
        "2017-02-01", "2017-03-15", "2017-05-03", "2017-06-14",
        "2017-07-26", "2017-09-20", "2017-11-01", "2017-12-13",
        # 2018
        "2018-01-31", "2018-03-21", "2018-05-02", "2018-06-13",
        "2018-08-01", "2018-09-26", "2018-11-08", "2018-12-19",
        # 2019
        "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19",
        "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11",
        # 2020 — includes two emergency cuts (Mar 3 and Mar 15)
        "2020-01-29", "2020-03-03", "2020-03-15", "2020-04-29",
        "2020-06-10", "2020-07-29", "2020-09-16", "2020-11-05",
        "2020-12-16",
        # 2021
        "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
        "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
        # 2022
        "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
        "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
        # 2023
        "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
        "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
        # 2024
        "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
        "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
        # 2025
        "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
        "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
        # 2026 (scheduled — update as confirmed)
        "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
    ]
])


def days_to_next_fomc(target_date):
    """Business-day-agnostic distance to next FOMC meeting."""
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    future = [d for d in FOMC_DATES if d >= target_date]
    if not future:
        return 100
    return (future[0] - target_date).days

"""
config.py — Central configuration for the Tarasque model pipeline.

All tunable parameters live here as dataclasses. No magic numbers in other modules.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional

from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Sector-ETF mapping (GICS sector code → sector ETF ticker)
# Used in Phase 2 for sector-specific feature selection per stock.
# ---------------------------------------------------------------------------
SECTOR_ETF_MAP: Dict[str, str] = {
    "10": "XLE",   # Energy
    "15": "XLB",   # Materials
    "20": "XLI",   # Industrials
    "25": "XLY",   # Consumer Discretionary
    "30": "XLP",   # Consumer Staples
    "35": "XLV",   # Health Care
    "40": "XLF",   # Financials
    "45": "XLK",   # Information Technology
    "50": "XLC",   # Communication Services
    "55": "XLU",   # Utilities
    "60": "XLRE",  # Real Estate
}


@dataclass
class DataConfig:
    """Data source and storage configuration."""

    # Parquet root — configurable per machine via env var or constructor arg
    base_dir: Path = field(default_factory=lambda: Path(
        os.getenv("TARASQUE_BASE_DIR", "D:/Tarasque_DB")
    ))

    start_date: str = "2011-01-01"
    end_date: str = "today"  # resolved at query time

    # ── Target universe ──────────────────────────────────────────────────
    # 93-ticker production universe (full vsurfd coverage minus known bad data):
    #   LIN  — R²=0.94 leakage artifact
    #   OXY  — RMSE explosion (data quality)
    #   VZ   — beta outlier, model finds no signal
    #   META — confirmed issues
    tickers: List[str] = field(default_factory=lambda: [
        "AAPL", "ABBV", "ABT",  "ADBE", "AEP",  "AMAT", "AMD",  "AMGN",
        "AMT",  "AMZN", "APD",  "AVGO", "AXP",  "BA",   "BAC",  "BKNG",
        "BLK",  "BMY",  "C",    "CAT",  "CCI",  "CL",   "CMCSA","COP",
        "COST", "CRM",  "CSCO", "CVS",  "CVX",  "D",    "DE",   "DIS",
        "DOW",  "DUK",  "EOG",  "EQIX", "F",    "FCX",  "FDX",  "GE",
        "GILD", "GM",   "GOOGL","GS",   "HD",   "HON",  "IBM",  "INTC",
        "JNJ",  "JPM",  "KO",   "LLY",  "LMT",  "LOW",  "MCD",
        "MMM",  "MO",   "MPC",  "MRK",  "MS",   "MSFT", "MU",
        "NEE",  "NEM",  "NFLX", "NKE",  "NOC",  "NVDA", "ORCL",
        "PEP",  "PFE",  "PG",   "PLD",  "PM",   "PSX",  "QCOM", "RTX",
        "SBUX", "SCHW", "SLB",  "SO",   "SPG",  "T",    "TGT",  "TMO",
        "TSLA", "TXN",  "UNH",  "UPS",  "USB",  "WFC",  "WMT",
        "XOM",
    ])

    # ── Factor ETFs ──────────────────────────────────────────────────────
    # ALL ETFs queried from WRDS (stored for future phases).
    # Must include ALL 11 GICS sector ETFs from SECTOR_ETF_MAP so that
    # corr_sector_21d / sector_wedge features don't silently fall back to SPY.
    all_factor_etfs: List[str] = field(default_factory=lambda: [
        "SPY", "VIXY", "HYG", "USO", "TLT", "UUP",        # Core 6
        "XLK", "XLF", "XLE", "XLV", "XLP", "QQQ",          # Sector + broad
        "XLI", "XLB", "XLY", "XLU", "XLRE", "XLC",         # Remaining GICS sectors
        "IEI", "IEF", "GLD", "IWM", "EEM", "MCHI",         # Rates / intl
        "IYR",                                               # Real estate (legacy)
    ])

    # Initial 6 used for model features (Phase 1 — avoids multicollinearity).
    initial_factor_etfs: List[str] = field(default_factory=lambda: [
        "VIXY", "HYG", "USO", "TLT", "UUP", "SPY",
    ])

    # ── OptionMetrics vol surface grid ───────────────────────────────────
    vsurfd_days: List[int] = field(default_factory=lambda: [30, 60, 91, 182])
    vsurfd_deltas: List[int] = field(default_factory=lambda: [10, 25, 50, -25, -10])

    # ── FRED series codes → human-readable labels ────────────────────────
    fred_series: Dict[str, str] = field(default_factory=lambda: {
        "DGS2":            "treasury_2y",
        "DGS10":           "treasury_10y",
        "DGS3MO":          "treasury_3mo",
        "DTB3":            "tbill_3mo",
        "T5YIE":           "breakeven_5y",
        "T10YIE":          "breakeven_10y",
        "BAMLH0A0HYM2":   "hy_spread",
        "DFF":             "fed_funds",
        "DTWEXBGS":        "dollar_index",
    })

    # ── Filters ──────────────────────────────────────────────────────────
    min_daily_volume_usd: float = 50_000_000.0


@dataclass
class ModelConfig:
    """Model hyperparameters and training configuration."""

    horizons: List[int] = field(default_factory=lambda: [21, 63, 126])

    # Realized vol windows — 126 needed for clean H=126 target (no overlap)
    rv_windows: List[int] = field(default_factory=lambda: [5, 10, 21, 63, 126])

    # Vol estimator for rv_* features AND rv_TARGET.
    # 'gk' = Garman-Klass (intraday only, misses overnight gaps — original default)
    # 'yz' = Yang-Zhang (overnight + open-to-close + Rogers-Satchell intraday;
    #        captures earnings/event overnight moves that GK misses)
    # Switch to 'yz' after 2026-05-27 reframe: GK target undermeasures earnings vol
    # and structurally underweights event_gravity features in loss.
    vol_estimator: str = "gk"   # "gk" | "yz"

    # Walk-forward analysis
    wfa_splits: int = 5

    # ── XGBoost — tuned via Optuna (2026-04-25, JPM 100T + AAPL 60T) ────────
    # Unanimous changes vs prior defaults (depth=4, n_est=100, alpha=0.01, lambda=1.0):
    #   depth 4→3, n_est 100→225, reg_alpha 0.01→0.15, reg_lambda 1.0→0.27,
    #   gamma 0.1→0.20, subsample 1.0→0.75, colsample 0.8→0.70.
    # Conflicting params (JPM/AAPL disagreed — used compromise):
    #   learning_rate kept 0.05 (JPM=0.025, AAPL=0.111)
    #   min_child_weight=4 (JPM=8, AAPL=1)
    #   colsample_bytree=0.70 (JPM=0.585, AAPL=0.879)
    xgb_params: Dict = field(default_factory=lambda: {
        "n_estimators": 225,
        "max_depth": 3,
        "learning_rate": 0.05,
        "reg_alpha": 0.15,
        "reg_lambda": 0.27,
        "gamma": 0.20,
        "colsample_bytree": 0.70,
        "min_child_weight": 4,
        "subsample": 0.75,
        "n_jobs": 2,            # CUDA does the work; 2 CPU threads for coordination
        "device": "cuda",       # GPU if available; auto-fallback in models.py
        "tree_method": "hist",  # Required for GPU mode
    })

    # ── Random Forest — tuned via Optuna (2026-04-25) ────────────────────
    # Both JPM and AAPL agreed: n_est 100→150, min_samples_leaf 5→12.
    # 5950X (32 logical): parallel_tickers=4 × n_jobs=4 = 16 CPU threads for RF.
    rf_params: Dict = field(default_factory=lambda: {
        "n_estimators": 150,
        "min_samples_leaf": 12,
        "n_jobs": 4,
    })

    # ── ElasticNetCV ─────────────────────────────────────────────────────
    # Matches rf_params n_jobs so total CPU threads stay bounded.
    lasso_n_jobs: int = 4   # field name kept for backwards compat

    # ── GARCH ────────────────────────────────────────────────────────────
    garch_dist: str = "skewt"

    # Exponential recency weighting — lambda=0 disables (uniform weights).
    # Lambda > 0 upweights recent observations. Half-life ≈ ln(2)/lambda BDays.
    # Targets corpus-wide H=63/H=126 over-forecast cluster (β<0.7) where the
    # model anchors to training-era vol levels that no longer apply. Try 0.0005
    # (half-life ~5.5 yrs) before 0.001 (~2.75 yrs).
    exp_weight_lambda: float = 0.0

    # Vol-rank weighting (orthogonal to lambda) — alpha=0 disables.
    # w = 1 + alpha * y.rank(pct=True). Upweights high-vol training observations.
    # Targets the AAPL-style under-forecast (β>1) cluster only — would WORSEN
    # the over-forecast cluster, so use alongside exp-weighting only with care.
    # Try alpha=1.0 (top decile gets ~2x weight) for a canary.
    vol_weight_alpha: float = 0.0

    # ── Ensemble ─────────────────────────────────────────────────────────
    # Floor prevents a single model from dominating the blend.
    min_ensemble_weight: float = 0.10

    # ── Quantile forecasting ──────────────────────────────────────────────
    # Trains a parallel XGBoost at each tau alongside the ensemble.
    # XGBoost >= 2.0 required (objective="reg:quantileerror").
    # tau=0.15 → P15 vol floor (lower bound estimate).
    # Left tail is structurally more forecastable than the right — low-vol regimes
    # are driven by observable, persistent factors (GARCH, HYG, VIXY, RV windows).
    # Right tail is dominated by unobserved shocks (earnings, macro surprises) that
    # no lagged feature can capture, making coverage calibration there intractable.
    # Set to [] to disable quantile forecasting entirely.
    quantile_alphas: List[float] = field(default_factory=lambda: [0.15])


@dataclass
class BacktestConfig:
    """Backtest and iteration parameters."""

    window_type: str = "expanding"       # "expanding" or "rolling"
    rolling_window_days: int = 756       # 3 years if rolling
    step_days: int = 20                  # 4 trading weeks; production retrain cadence

    # Ticker-level parallelism: number of tickers to process simultaneously.
    # 5950X (32 logical) + GTX 1070: 4 workers keeps raw_data memory copies within 32GB.
    # 4 workers × (RF n_jobs=4 + Lasso n_jobs=4) = 32 CPU threads. XGB uses GPU.
    parallel_tickers: int = 4

    metrics: List[str] = field(default_factory=lambda: [
        "rmse", "mincer_zarnowitz", "qlike", "event_capture",
    ])

    results_dir: Path = field(default_factory=lambda: Path("model/pipeline/results"))


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_config(
    base_dir: Optional[str] = None,
) -> tuple:
    """
    Load .env and return (DataConfig, ModelConfig, BacktestConfig).

    Parameters
    ----------
    base_dir : str, optional
        Override for the Parquet storage root.  Falls back to env var
        ``TARASQUE_BASE_DIR``, then ``D:/Tarasque_DB``.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=env_path)

    dc = DataConfig()
    if base_dir is not None:
        dc.base_dir = Path(base_dir)

    return dc, ModelConfig(), BacktestConfig()

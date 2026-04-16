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
    # ── v6 sample run (split-fix + GARCH feature validation) ────────────
    # 6 tickers chosen for diagnostic coverage:
    #   AAPL, AMZN — split-fix validation (multiple large splits)
    #   JPM, XOM   — stable v5 canaries for baseline comparison
    #   BA         — best v5 beta improvement; confirm it holds with GARCH
    #   D          — worst v5 regression; GARCH mean-reversion should help
    tickers: List[str] = field(default_factory=lambda: [
        "AAPL", "AMZN", "JPM", "XOM", "BA", "D",
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

    # Garman-Klass RV windows — 126 needed for clean H=126 target (no overlap)
    rv_windows: List[int] = field(default_factory=lambda: [5, 10, 21, 63, 126])

    # Walk-forward analysis
    wfa_splits: int = 5

    # ── XGBoost (from volarbmodel_backtest.py:364) ───────────────────────
    xgb_params: Dict = field(default_factory=lambda: {
        "n_estimators": 100,
        "max_depth": 4,
        "learning_rate": 0.05,
        "reg_alpha": 0.01,
        "gamma": 0.1,
        "colsample_bytree": 0.8,
        "reg_lambda": 1.0,
        "n_jobs": 2,            # CUDA does the work; 2 CPU threads for coordination
        "device": "cuda",       # GPU if available; auto-fallback in models.py
        "tree_method": "hist",  # Required for GPU mode
    })

    # ── Random Forest ─────────────────────────────────────────────────────
    # 5950X (32 logical): parallel_tickers=8 × n_jobs=4 = 32 CPU threads total
    rf_params: Dict = field(default_factory=lambda: {
        "n_estimators": 100,
        "min_samples_leaf": 5,
        "n_jobs": 4,
    })

    # ── LassoCV ──────────────────────────────────────────────────────────
    # Matches rf_params n_jobs so total CPU threads stay bounded.
    lasso_n_jobs: int = 4

    # ── GARCH ────────────────────────────────────────────────────────────
    garch_dist: str = "skewt"

    # Exponential recency weighting — lambda=0 disables (uniform weights).
    exp_weight_lambda: float = 0.0

    # ── Ensemble ─────────────────────────────────────────────────────────
    # Floor prevents a single model from dominating the blend.
    min_ensemble_weight: float = 0.10


@dataclass
class BacktestConfig:
    """Backtest and iteration parameters."""

    window_type: str = "expanding"       # "expanding" or "rolling"
    rolling_window_days: int = 756       # 3 years if rolling
    step_days: int = 25                  # retrain every ~1.25mo

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

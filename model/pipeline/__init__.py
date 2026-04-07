"""
Tarasque Model Pipeline — modular volatility forecasting framework.

Modules:
    config      - Central configuration (DataConfig, ModelConfig, BacktestConfig)
    data_loader - WRDS queries + Alpaca continuation + Parquet storage
    features    - Feature engineering from raw data to model-ready matrix
    models      - XGB/RF/LassoCV/GARCH ensemble with WFA
    backtest    - Walk-forward backtesting engine
    utils       - Shared helpers (BS pricing, FOMC calendar, etc.)
    run         - CLI orchestrator
"""

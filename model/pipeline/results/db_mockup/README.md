# Tarasque Equity Page — Database Mockup

Generated from real recent run data (v10 24-ticker, v9 canary, v6 corpus) to
verify the schema design supports every visualization on /equity/:symbol.

## Tables

| File | Table | Notes |
|---|---|---|
| 01_securities.csv | securities | Extended with sector, exclusion reason, history bounds. 91 active + 4 excluded. |
| 02_volatility_history_sample.csv | volatility_history | Wide format: rv, iv (4 DTEs), vrp_wedge + EWMA, pfv at 3 horizons (raw/q15/calibrated). Sample: AAPL last 20d + others. |
| 03_prices_history.csv | prices_history | Equity OHLCV, backend cache, daily ETL. Pulled fresh from yfinance. |
| 04_options_chain_sample.csv | options_chain | Snapshot per (security, snapshot_date, expiry, strike, type). Daily backend pull. |
| 05_ai_overview_equity.csv | ai_overview_equity | Hybrid storage — top-level (headline, risk_tier) + JSONB content blob. |
| 06_shap_snapshot.csv | shap_snapshot | Feature contributions as JSONB; one row per (security, retrain, horizon). |
| 07_model_runs.csv | model_runs | Registry — every prediction row references a model_run_id. |
| 08_get_distribution_rpc_output.csv | get_distribution() RPC | Sample output: histogram bins for stock/sector/market in one call. |

## Reading the volatility_history sample

Each row is one (ticker, date) snapshot. The 16 vol-related columns answer
every chart on the equity page:

- VRP EWMA panel below price       -> vrp_wedge_ewma_21d
- Term-structure overlay           -> pfv_21/63/126 + iv_atm_30d/60d/91d/182d
- Distribution charts              -> any of the columns, ranked over history
- Forecast bands (options chart)   -> pfv_21 + dte interpolation
- Calibration overlay (production) -> pfv_cal_*

## Notes

- iv_atm_30d in the sample is reconstructed as vrp_wedge + y_true since the prediction
  CSVs do not carry raw IV. In production the IV ETL writes it directly.
- iv_atm_60d/91d/182d are NULL in the sample, populated from the OptionMetrics vsurfd ETL.
- AI overview content is synthetic but its structure (headline + risk_tier top-level,
  content as JSONB) reflects the production schema.
- SHAP feature_data is synthetic (placeholder values).
- Options chain is a real yfinance pull for AAPL nearest expiries when available.

## How a frontend page load consumes this

GET /api/equity/AAPL -> backend issues:
1. SELECT * FROM securities WHERE symbol = AAPL
2. SELECT * FROM volatility_history WHERE security_id = 1 AND date >= NOW() - 5 years
3. SELECT * FROM prices_history WHERE security_id = 1 AND date >= NOW() - 1 year
4. SELECT * FROM options_chain WHERE security_id = 1 AND snapshot_date = (latest)
5. SELECT * FROM ai_overview_equity WHERE security_id = 1 AND flagged = FALSE LIMIT 1
6. SELECT * FROM shap_snapshot WHERE security_id = 1 AND retrain_date = (latest)
7. SELECT * FROM get_distribution(1, rv)  -- and one per metric on toggle

All assemble into one composite payload. Single React-Query hook on the page mount.

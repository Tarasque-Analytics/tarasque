INSERT INTO securities (security_id, ticker, gics_sector, gics_industry, sector_etf, active, min_history_date, last_model_run)
VALUES 
  (320193, 'AAPL', 'Information Technology', 'Technology Hardware & Equipment', 'QQQ', true, CURRENT_DATE, now()),
  (166080, 'MSFT', 'Information Technology', 'Software & Services', 'QQQ', true, CURRENT_DATE, now()),
  (789019, 'GOOGL', 'Communication Services', 'Internet Services & Infrastructure', 'QQQ', true, CURRENT_DATE, now()),
  (902192, 'AMZN', 'Consumer Discretionary', 'Internet & Direct Marketing Retail', 'XLY', true, CURRENT_DATE, now()),
  (12345, 'TSLA', 'Consumer Discretionary', 'Automobiles', 'XLY', true, CURRENT_DATE, now()),
  (67890, 'META', 'Communication Services', 'Interactive Media & Services', 'XLC', true, CURRENT_DATE, now()),
  (11223, 'NFLX', 'Communication Services', 'Media & Entertainment', 'XLC', true, CURRENT_DATE, now()),
  (44556, 'JPM', 'Financials', 'Banks', 'XLF', true, CURRENT_DATE, now()),
  (77889, 'JNJ', 'Health Care', 'Pharmaceuticals, Biotechnology & Life Sciences', 'XLV', true, CURRENT_DATE, now()),
  (99001, 'PG', 'Consumer Staples', 'Household & Personal Products', 'XLP', true, CURRENT_DATE, now());

-- Volatility History (5 days of data for AAPL and MSFT)
INSERT INTO volatility_history (security_id, date, rv, ewma_vol, iv_atm_30d, iv_atm_60d, iv_atm_91d, iv_atm_182d, vrp_wedge, vrp_wedge_ewma_21d, pfv_21, pfv_63, pfv_126, pfv_q15_21, pfv_q15_63, pfv_q15_126, pfv_cal_21, pfv_cal_63, pfv_cal_126, next_earnings_date, days_to_earnings, next_dividend_date, days_to_dividend)
VALUES
  (320193, CURRENT_DATE - 4, 0.18, 0.19, 0.22, 0.20, 0.19, 0.18, 0.04, 0.03, 0.85, 0.82, 0.80, 0.75, 0.70, 0.68, 0.88, 0.85, 0.83, CURRENT_DATE + 30, 30, CURRENT_DATE + 60, 60),
  (320193, CURRENT_DATE - 3, 0.19, 0.19, 0.23, 0.21, 0.20, 0.19, 0.05, 0.04, 0.86, 0.83, 0.81, 0.76, 0.71, 0.69, 0.89, 0.86, 0.84, CURRENT_DATE + 30, 30, CURRENT_DATE + 60, 60),
  (320193, CURRENT_DATE - 2, 0.17, 0.18, 0.21, 0.20, 0.19, 0.18, 0.03, 0.03, 0.84, 0.81, 0.79, 0.74, 0.69, 0.67, 0.87, 0.84, 0.82, CURRENT_DATE + 30, 30, CURRENT_DATE + 60, 60),
  (320193, CURRENT_DATE - 1, 0.20, 0.19, 0.24, 0.22, 0.20, 0.19, 0.06, 0.04, 0.87, 0.84, 0.82, 0.77, 0.72, 0.70, 0.90, 0.87, 0.85, CURRENT_DATE + 30, 30, CURRENT_DATE + 60, 60),
  (320193, CURRENT_DATE, 0.19, 0.19, 0.23, 0.21, 0.20, 0.19, 0.05, 0.04, 0.86, 0.83, 0.81, 0.76, 0.71, 0.69, 0.89, 0.86, 0.84, CURRENT_DATE + 30, 30, CURRENT_DATE + 60, 60),
  (166080, CURRENT_DATE - 2, 0.16, 0.17, 0.20, 0.19, 0.18, 0.17, 0.02, 0.02, 0.83, 0.80, 0.78, 0.73, 0.68, 0.66, 0.86, 0.83, 0.81, CURRENT_DATE + 25, 25, CURRENT_DATE + 90, 90),
  (166080, CURRENT_DATE - 1, 0.18, 0.17, 0.21, 0.20, 0.19, 0.18, 0.04, 0.03, 0.85, 0.82, 0.80, 0.75, 0.70, 0.68, 0.88, 0.85, 0.83, CURRENT_DATE + 25, 25, CURRENT_DATE + 90, 90),
  (166080, CURRENT_DATE, 0.17, 0.17, 0.20, 0.19, 0.18, 0.17, 0.03, 0.03, 0.84, 0.81, 0.79, 0.74, 0.69, 0.67, 0.87, 0.84, 0.82, CURRENT_DATE + 25, 25, CURRENT_DATE + 90, 90);

-- Price History (5 days for AAPL and MSFT)
INSERT INTO prices_history (security_id, date, open, high, low, close, adj_close, volume)
VALUES
  (320193, CURRENT_DATE - 4, 225.50, 228.75, 224.80, 227.50, 227.50, 45000000),
  (320193, CURRENT_DATE - 3, 227.75, 230.25, 226.50, 229.00, 229.00, 42000000),
  (320193, CURRENT_DATE - 2, 228.50, 232.00, 227.75, 231.50, 231.50, 48000000),
  (320193, CURRENT_DATE - 1, 231.25, 233.50, 230.00, 232.75, 232.75, 50000000),
  (320193, CURRENT_DATE, 232.50, 235.25, 231.50, 234.00, 234.00, 55000000),
  (166080, CURRENT_DATE - 4, 410.25, 415.50, 408.75, 413.50, 413.50, 20000000),
  (166080, CURRENT_DATE - 3, 413.75, 418.25, 412.00, 416.00, 416.00, 22000000),
  (166080, CURRENT_DATE - 2, 415.50, 420.75, 414.25, 419.50, 419.50, 24000000),
  (166080, CURRENT_DATE - 1, 418.75, 422.50, 417.00, 421.00, 421.00, 26000000),
  (166080, CURRENT_DATE, 420.50, 425.00, 419.25, 423.50, 423.50, 28000000);

-- Options Chain (ATM calls and puts for AAPL expiring in 30 days)
INSERT INTO options_chain (security_id, snapshot_date, expiry, strike, option_type, bid, ask, mid, last, volume, open_interest, iv, delta)
VALUES
  (320193, CURRENT_DATE, CURRENT_DATE + 30, 230.00, 'C', 4.50, 4.75, 4.625, 4.60, 5000, 50000, 0.23, 0.65),
  (320193, CURRENT_DATE, CURRENT_DATE + 30, 230.00, 'P', 2.25, 2.50, 2.375, 2.40, 3000, 35000, 0.23, -0.35),
  (320193, CURRENT_DATE, CURRENT_DATE + 30, 235.00, 'C', 2.00, 2.25, 2.125, 2.10, 2500, 25000, 0.22, 0.45),
  (320193, CURRENT_DATE, CURRENT_DATE + 30, 235.00, 'P', 4.50, 4.75, 4.625, 4.60, 1500, 15000, 0.22, -0.55),
  (320193, CURRENT_DATE, CURRENT_DATE + 60, 230.00, 'C', 6.25, 6.50, 6.375, 6.30, 3000, 40000, 0.20, 0.60),
  (320193, CURRENT_DATE, CURRENT_DATE + 60, 230.00, 'P', 4.00, 4.25, 4.125, 4.10, 2000, 30000, 0.20, -0.40);

-- SHAP Snapshot (feature importance data for AAPL, 3 horizons: 21/63/126)
INSERT INTO shap_snapshot (security_id, retrain_date, horizon, snapshot_date, base_value, predicted_value, feature_data)
VALUES
  (320193, CURRENT_DATE, 21, CURRENT_DATE, 0.19, 0.21, '{"iv_30d": 0.45, "rv_21d": 0.38, "vrp": 0.05, "vix": 0.42, "momentum": 0.12}'::jsonb),
  (320193, CURRENT_DATE, 63, CURRENT_DATE, 0.19, 0.20, '{"iv_30d": 0.42, "rv_21d": 0.35, "vrp": 0.04, "vix": 0.40, "momentum": 0.10}'::jsonb),
  (320193, CURRENT_DATE, 126, CURRENT_DATE, 0.19, 0.195, '{"iv_30d": 0.40, "rv_21d": 0.32, "vrp": 0.03, "vix": 0.38, "momentum": 0.08}'::jsonb);

-- Per-security events (event_history is keyed by security_id)
INSERT INTO event_history (security_id, event_date, event_type, scope, title, description, source)
VALUES
  (320193, CURRENT_DATE - 5, 'earnings', 'ticker', 'Apple Q2 Earnings', 'Apple reported strong iPhone sales with 15% YoY growth', 'Bloomberg'),
  (99001,  CURRENT_DATE - 1, 'dividend', 'ticker', 'Procter & Gamble Dividend Payment', 'Quarterly dividend of $0.92 per share paid', 'SEC'),
  (166080, CURRENT_DATE,     'earnings', 'ticker', 'Microsoft Q3 Earnings', 'Microsoft beats EPS expectations with AI growth driving revenue', 'MarketWatch');

-- Market-wide macro calendar (days-to-next-event feature; affects all securities)
-- Daily snapshots counting down to the next FOMC decision on CURRENT_DATE + 1.
INSERT INTO macro_calendar (date, event_type, days_to_event, event_date)
VALUES
  (CURRENT_DATE - 4, 'fomc', 5, CURRENT_DATE + 1),
  (CURRENT_DATE - 3, 'fomc', 4, CURRENT_DATE + 1),
  (CURRENT_DATE - 2, 'fomc', 3, CURRENT_DATE + 1),
  (CURRENT_DATE - 1, 'fomc', 2, CURRENT_DATE + 1),
  (CURRENT_DATE,     'fomc', 1, CURRENT_DATE + 1);

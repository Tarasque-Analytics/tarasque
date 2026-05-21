CREATE TABLE securities (
  security_id bigserial PRIMARY KEY,
  ticker text NOT NULL DEFAULT ''::text,
  gics_sector text NULL DEFAULT ''::text,
  gics_industry text NULL DEFAULT ''::text,
  sector_etf text NULL DEFAULT ''::text,
  active boolean NULL DEFAULT true,
  min_history_date date NULL,
  last_model_run timestamp without time zone NULL DEFAULT now()
);

CREATE TABLE model_runs (
    id              BIGSERIAL PRIMARY KEY,
    run_date        DATE NOT NULL,
    model_version   TEXT NOT NULL,
    spec_hash       TEXT,
    n_tickers       INT,
    horizons        INT[],
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE volatility_history (
    security_id          INT NOT NULL REFERENCES securities,
    date                 DATE NOT NULL,
    rv                   DOUBLE PRECISION,
    ewma_vol             DOUBLE PRECISION,
    iv_atm_30d           DOUBLE PRECISION,
    iv_atm_60d           DOUBLE PRECISION,
    iv_atm_91d           DOUBLE PRECISION,
    iv_atm_182d          DOUBLE PRECISION,
    vrp_wedge            DOUBLE PRECISION,
    vrp_wedge_ewma_21d   DOUBLE PRECISION,
    pfv_21               DOUBLE PRECISION,
    pfv_63               DOUBLE PRECISION,
    pfv_126              DOUBLE PRECISION,
    pfv_q15_21           DOUBLE PRECISION,
    pfv_q15_63           DOUBLE PRECISION,
    pfv_q15_126          DOUBLE PRECISION,
    pfv_cal_21           DOUBLE PRECISION,
    pfv_cal_63           DOUBLE PRECISION,
    pfv_cal_126          DOUBLE PRECISION,
    next_earnings_date   DATE,
    days_to_earnings     INT,
    next_dividend_date   DATE,
    days_to_dividend     INT,
    model_run_id         BIGINT REFERENCES model_runs,
    PRIMARY KEY (security_id, date)
);

CREATE INDEX idx_vol_security_date ON volatility_history (security_id, date DESC);

CREATE TABLE prices_history (
    security_id   INT NOT NULL REFERENCES securities,
    date          DATE NOT NULL,
    open          NUMERIC(12,4),
    high          NUMERIC(12,4),
    low           NUMERIC(12,4),
    close         NUMERIC(12,4),
    adj_close     NUMERIC(12,4),
    volume        BIGINT,
    PRIMARY KEY (security_id, date)
);

CREATE INDEX idx_prices_security_date ON prices_history (security_id, date DESC);

CREATE TABLE options_chain (
    id              BIGSERIAL PRIMARY KEY,
    security_id     INT NOT NULL REFERENCES securities,
    snapshot_date   DATE NOT NULL,
    expiry          DATE NOT NULL,
    strike          NUMERIC(10,2) NOT NULL,
    option_type     CHAR(1) NOT NULL CHECK (option_type IN ('C','P')),
    bid             NUMERIC(8,2),
    ask             NUMERIC(8,2),
    mid             NUMERIC(8,2),
    last            NUMERIC(8,2),
    volume          INT,
    open_interest   INT,
    iv              DOUBLE PRECISION,
    delta           DOUBLE PRECISION,
    UNIQUE (security_id, snapshot_date, expiry, strike, option_type)
);

CREATE INDEX idx_opt_security_snapshot ON options_chain (security_id, snapshot_date);
CREATE INDEX idx_opt_security_expiry   ON options_chain (security_id, snapshot_date, expiry);

CREATE TABLE ai_overview (
    id              BIGSERIAL PRIMARY KEY,
    security_id     INT NOT NULL REFERENCES securities,
    date            DATE NOT NULL,
    model_ver       TEXT NOT NULL,
    prompt_ver      TEXT NOT NULL,
    headline        TEXT NOT NULL,
    risk_tier       TEXT,
    content         JSONB NOT NULL,
    input_hash      TEXT,
    input_tokens    INT,
    output_tokens   INT,
    generated_at    TIMESTAMPTZ DEFAULT NOW(),
    flagged         BOOLEAN DEFAULT FALSE,
    flagged_reason  TEXT,
    UNIQUE (security_id, date, model_ver, prompt_ver)
);

CREATE INDEX idx_ai_eq_recent
  ON ai_overview (security_id, date DESC)
  WHERE flagged = FALSE;

CREATE TABLE shap_snapshot (
    security_id        INT NOT NULL REFERENCES securities,
    retrain_date       DATE NOT NULL,
    horizon            INT NOT NULL,
    snapshot_date      DATE NOT NULL,
    base_value         DOUBLE PRECISION,
    predicted_value    DOUBLE PRECISION,
    feature_data       JSONB NOT NULL,
    PRIMARY KEY (security_id, retrain_date, horizon, snapshot_date)
);

CREATE INDEX idx_shap_recent
  ON shap_snapshot (security_id, snapshot_date DESC, horizon);

CREATE TABLE events_history (
    id            BIGSERIAL PRIMARY KEY,
    event_date    DATE NOT NULL,
    event_type    TEXT NOT NULL,        -- 'earnings' | 'dividend' | 'fomc'
    severity      TEXT,                 -- 'crisis' | 'major' | 'notable'
    scope         TEXT NOT NULL,        -- 'market' | 'sector' | 'ticker'
    scope_value   TEXT,                 -- NULL for market; sector name; ticker symbol
    title         TEXT NOT NULL,
    description   TEXT,
    source        TEXT
);

CREATE INDEX idx_events_date  ON events_history (event_date);
CREATE INDEX idx_events_scope ON events_history (scope, scope_value);

CREATE FUNCTION get_distribution(
    p_security_id    INT,
    p_metric         TEXT,    -- 'rv' | 'iv_atm_30d' | 'vrp_wedge' | 'pfv_cal_21'
    p_lookback_days  INT DEFAULT 1260
) RETURNS TABLE (
    scope               TEXT,    -- 'stock' | 'sector' | 'market'
    bin_low             DOUBLE PRECISION,
    bin_high            DOUBLE PRECISION,
    count               INT,
    current_value       DOUBLE PRECISION,
    current_percentile  DOUBLE PRECISION
) AS $$
BEGIN
    -- Placeholder function - to be implemented with actual distribution logic
    RETURN QUERY SELECT 'stock'::TEXT, 0::DOUBLE PRECISION, 0::DOUBLE PRECISION, 0::INT, 0::DOUBLE PRECISION, 0::DOUBLE PRECISION WHERE FALSE;
END;
$$ LANGUAGE plpgsql;


CREATE TABLE user_dashboard (
  user_id UUID NOT NULL REFERENCES auth.identities(id) PRIMARY KEY,
  watchlist JSONB NOT NULL DEFAULT '[]'::jsonb
);





-- Enable Row Level Security on all tables

-- 1. Securities table
ALTER TABLE securities ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow public read access to securities"
  ON securities FOR SELECT
  TO public
  USING (true);

CREATE POLICY "Restrict write access to authenticated users"
  ON securities FOR INSERT
  TO authenticated
  WITH CHECK (false);

CREATE POLICY "Restrict update access to authenticated users"
  ON securities FOR UPDATE
  TO authenticated
  USING (false);

CREATE POLICY "Restrict delete access to authenticated users"
  ON securities FOR DELETE
  TO authenticated
  USING (false);

-- 2. Volatility History table
ALTER TABLE volatility_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow public read access to volatility_history"
  ON volatility_history FOR SELECT
  TO public
  USING (true);

CREATE POLICY "Restrict write access to authenticated users"
  ON volatility_history FOR INSERT
  TO authenticated
  WITH CHECK (false);

CREATE POLICY "Restrict update access to authenticated users"
  ON volatility_history FOR UPDATE
  TO authenticated
  USING (false);

CREATE POLICY "Restrict delete access to authenticated users"
  ON volatility_history FOR DELETE
  TO authenticated
  USING (false);

-- 3. Prices History table
ALTER TABLE prices_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow public read access to prices_history"
  ON prices_history FOR SELECT
  TO public
  USING (true);

CREATE POLICY "Restrict write access to authenticated users"
  ON prices_history FOR INSERT
  TO authenticated
  WITH CHECK (false);

CREATE POLICY "Restrict update access to authenticated users"
  ON prices_history FOR UPDATE
  TO authenticated
  USING (false);

CREATE POLICY "Restrict delete access to authenticated users"
  ON prices_history FOR DELETE
  TO authenticated
  USING (false);

-- 4. Options Chain table
ALTER TABLE options_chain ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow public read access to options_chain"
  ON options_chain FOR SELECT
  TO public
  USING (true);

CREATE POLICY "Restrict write access to authenticated users"
  ON options_chain FOR INSERT
  TO authenticated
  WITH CHECK (false);

CREATE POLICY "Restrict update access to authenticated users"
  ON options_chain FOR UPDATE
  TO authenticated
  USING (false);

CREATE POLICY "Restrict delete access to authenticated users"
  ON options_chain FOR DELETE
  TO authenticated
  USING (false);

-- 5. SHAP Snapshot table
ALTER TABLE shap_snapshot ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow public read access to shap_snapshot"
  ON shap_snapshot FOR SELECT
  TO public
  USING (true);

CREATE POLICY "Restrict write access to authenticated users"
  ON shap_snapshot FOR INSERT
  TO authenticated
  WITH CHECK (false);

CREATE POLICY "Restrict update access to authenticated users"
  ON shap_snapshot FOR UPDATE
  TO authenticated
  USING (false);

CREATE POLICY "Restrict delete access to authenticated users"
  ON shap_snapshot FOR DELETE
  TO authenticated
  USING (false);

-- 6. Events History table
ALTER TABLE events_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow public read access to events_history"
  ON events_history FOR SELECT
  TO public
  USING (true);

CREATE POLICY "Restrict write access to authenticated users"
  ON events_history FOR INSERT
  TO authenticated
  WITH CHECK (false);

CREATE POLICY "Restrict update access to authenticated users"
  ON events_history FOR UPDATE
  TO authenticated
  USING (false);

CREATE POLICY "Restrict delete access to authenticated users"
  ON events_history FOR DELETE
  TO authenticated
  USING (false);

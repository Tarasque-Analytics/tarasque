-- ============================================================================
-- Tarasque  Migration 001 — Schema fixes for model-side Supabase integration
-- ============================================================================
-- Author:  model side (Leo)
-- Date:    2026-05-10
-- Scope:   ADDITIVE ONLY. No data destruction. Idempotent where possible.
--
-- This migration brings the current public schema in line with the model's
-- export contract (see model/SUPABASE_SCHEMA.md). All major bugs from the
-- previous schema (GENERATED ALWAYS AS IDENTITY on FK columns, broken PK on
-- prices_history, etc.) have already been fixed by the web side — this
-- migration only adds what's missing.
--
-- Run order: top to bottom. All statements are idempotent or use IF EXISTS /
-- IF NOT EXISTS guards. Safe to re-run.
--
-- After this migration runs, the model-side ETL (model/pipeline/db.py) can
-- write the full output bundle to Supabase. Until then, writes will fail
-- with clear errors thanks to the verify_schema() pre-flight check.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1. securities — add excluded_reason
-- ----------------------------------------------------------------------------
ALTER TABLE public.securities
    ADD COLUMN IF NOT EXISTS excluded_reason TEXT;

COMMENT ON COLUMN public.securities.excluded_reason IS
    'Free-text reason a ticker is inactive (e.g., merger artifact, IPO recency).
     NULL for active tickers. Frontend filters universe by active=TRUE.';


-- ----------------------------------------------------------------------------
-- 2. model_runs — new registry table
-- ----------------------------------------------------------------------------
-- One row per backtest run. Every prediction row in volatility_history
-- references the run that produced it via model_run_id.

CREATE TABLE IF NOT EXISTS public.model_runs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_date        DATE NOT NULL,
    model_version   TEXT NOT NULL,
    spec_hash       TEXT,
    n_tickers       INT,
    horizons        INT[],
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE  public.model_runs IS 'Registry of model retrains / corpus runs.';
COMMENT ON COLUMN public.model_runs.spec_hash IS 'Git commit hash producing the spec for this run.';


-- ----------------------------------------------------------------------------
-- 3. volatility_history — add 11 missing columns
-- ----------------------------------------------------------------------------
ALTER TABLE public.volatility_history
    ADD COLUMN IF NOT EXISTS ewma_vol            DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS iv_atm_30d          DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS iv_atm_60d          DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS iv_atm_91d          DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS iv_atm_182d         DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS vrp_wedge_ewma_21d  DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS next_earnings_date  DATE,
    ADD COLUMN IF NOT EXISTS days_to_earnings    INTEGER,
    ADD COLUMN IF NOT EXISTS next_dividend_date  DATE,
    ADD COLUMN IF NOT EXISTS days_to_dividend    INTEGER,
    ADD COLUMN IF NOT EXISTS model_run_id        BIGINT;

-- Backfill iv_atm_30d from the existing iv_atm column so downstream queries
-- don't break. The single iv_atm column stays for backwards compatibility
-- and can be deprecated after the frontend stops reading from it.
UPDATE public.volatility_history
SET iv_atm_30d = iv_atm
WHERE iv_atm_30d IS NULL AND iv_atm IS NOT NULL;

-- FK to model_runs (added after model_runs exists). Use NOT VALID so existing
-- NULL model_run_id rows don't trigger validation errors; new rows enforce it.
ALTER TABLE public.volatility_history
    ADD CONSTRAINT volatility_history_model_run_id_fkey
    FOREIGN KEY (model_run_id) REFERENCES public.model_runs(id)
    NOT VALID;

COMMENT ON COLUMN public.volatility_history.iv_atm_30d  IS 'ATM IV, 30 DTE, delta=50';
COMMENT ON COLUMN public.volatility_history.iv_atm_60d  IS 'ATM IV, 60 DTE, delta=50';
COMMENT ON COLUMN public.volatility_history.iv_atm_91d  IS 'ATM IV, 91 DTE, delta=50';
COMMENT ON COLUMN public.volatility_history.iv_atm_182d IS 'ATM IV, 182 DTE, delta=50';
COMMENT ON COLUMN public.volatility_history.vrp_wedge_ewma_21d IS '21d EWMA of vrp_wedge (IV30d - RV)';


-- ----------------------------------------------------------------------------
-- 4. ai_overview — add 5 missing columns + uniqueness constraint
-- ----------------------------------------------------------------------------
ALTER TABLE public.ai_overview
    ADD COLUMN IF NOT EXISTS risk_tier       TEXT,
    ADD COLUMN IF NOT EXISTS input_hash      TEXT,
    ADD COLUMN IF NOT EXISTS input_tokens    INTEGER,
    ADD COLUMN IF NOT EXISTS output_tokens   INTEGER,
    ADD COLUMN IF NOT EXISTS flagged_reason  TEXT;

-- Uniqueness: only one overview row per (security, date, model, prompt).
-- This is what makes upserts idempotent.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ai_overview_unique'
    ) THEN
        ALTER TABLE public.ai_overview
            ADD CONSTRAINT ai_overview_unique
            UNIQUE (security_id, date, model_ver, prompt_ver);
    END IF;
END $$;

COMMENT ON COLUMN public.ai_overview.risk_tier IS
    'Top-level extracted risk classification for dashboard filtering.
     Values: Suppressed | Normal | Elevated | Stress | Crisis';
COMMENT ON COLUMN public.ai_overview.input_hash IS
    'Hash of the input signal set used to generate this overview.
     Used to skip regeneration when underlying signals are unchanged.';


-- ----------------------------------------------------------------------------
-- 5. options_chain — add uniqueness constraint
-- ----------------------------------------------------------------------------
-- Prevents the daily-ETL from duplicating the chain on rerun.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'options_chain_unique'
    ) THEN
        ALTER TABLE public.options_chain
            ADD CONSTRAINT options_chain_unique
            UNIQUE (security_id, snapshot_date, expiry, strike, option_type);
    END IF;
END $$;


-- ----------------------------------------------------------------------------
-- 6. shap_snapshot — fix PK to include snapshot_date
-- ----------------------------------------------------------------------------
-- Current PK is (security_id, retrain_date, horizon) which limits each
-- (ticker, retrain, horizon) to ONE snapshot_date. We need to accumulate
-- daily SHAP rows under the same retrain.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'shap_snapshot_pkey'
          AND conrelid = 'public.shap_snapshot'::regclass
    ) THEN
        ALTER TABLE public.shap_snapshot DROP CONSTRAINT shap_snapshot_pkey;
        ALTER TABLE public.shap_snapshot
            ADD CONSTRAINT shap_snapshot_pkey
            PRIMARY KEY (security_id, retrain_date, horizon, snapshot_date);
    END IF;
END $$;


-- ----------------------------------------------------------------------------
-- 7. macro_calendar — new forward-event table
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.macro_calendar (
    date           DATE NOT NULL,
    event_type     TEXT NOT NULL,                -- 'fomc' | 'cpi' | 'nfp' | ...
    event_date     DATE NOT NULL,
    days_to_event  INTEGER,
    PRIMARY KEY (date, event_type)
);

COMMENT ON TABLE public.macro_calendar IS
    'Forward-looking macro event dates (FOMC, CPI, NFP) keyed by (date, event_type).
     One row per (date, event_type) — universe-wide, reused by every ticker.';


-- ----------------------------------------------------------------------------
-- 8. Indexes
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_vol_security_date
    ON public.volatility_history (security_id, date DESC);

CREATE INDEX IF NOT EXISTS idx_prices_security_date
    ON public.prices_history (security_id, date DESC);

CREATE INDEX IF NOT EXISTS idx_opt_security_snapshot
    ON public.options_chain (security_id, snapshot_date);

CREATE INDEX IF NOT EXISTS idx_opt_security_expiry
    ON public.options_chain (security_id, snapshot_date, expiry);

CREATE INDEX IF NOT EXISTS idx_ai_recent
    ON public.ai_overview (security_id, date DESC)
    WHERE flagged = FALSE;

CREATE INDEX IF NOT EXISTS idx_shap_recent
    ON public.shap_snapshot (security_id, snapshot_date DESC, horizon);

CREATE INDEX IF NOT EXISTS idx_events_date
    ON public.events_history (event_date);

CREATE INDEX IF NOT EXISTS idx_events_scope
    ON public.events_history (scope, scope_value);


-- ----------------------------------------------------------------------------
-- 9. get_distribution() RPC — stub
-- ----------------------------------------------------------------------------
-- Frontend's distribution panel calls this with (security_id, metric).
-- Returns 30 bins × 3 scopes (stock/sector/market) in a single payload.
-- Stub body provided here so the function exists for frontend wiring;
-- final body should use width_bucket() over volatility_history.
-- See model/SUPABASE_SCHEMA.md §4.10 for the full spec.

CREATE OR REPLACE FUNCTION public.get_distribution(
    p_security_id    BIGINT,
    p_metric         TEXT,
    p_lookback_days  INT DEFAULT 1260
) RETURNS TABLE (
    scope               TEXT,
    bin_low             DOUBLE PRECISION,
    bin_high            DOUBLE PRECISION,
    count               INTEGER,
    current_value       DOUBLE PRECISION,
    current_percentile  DOUBLE PRECISION
)
LANGUAGE plpgsql
AS $$
BEGIN
    -- TODO (web side): implement using width_bucket() over volatility_history.
    -- Inputs: p_security_id, p_metric (column name in volatility_history),
    --         p_lookback_days.
    -- Output rows for scope IN ('stock', 'sector', 'market'), 30 bins each.
    RAISE NOTICE 'get_distribution() not yet implemented';
    RETURN;
END;
$$;

COMMENT ON FUNCTION public.get_distribution IS
    'Returns histogram bins for a metric across stock/sector/market scopes.
     Stub — implementation pending (see model/SUPABASE_SCHEMA.md §4.10).';


-- ----------------------------------------------------------------------------
-- DONE
-- ----------------------------------------------------------------------------
-- After running this migration:
--   1. Verify with: SELECT verify_schema_state();  -- (web-side helper, optional)
--   2. Model-side ETL: python -m model.pipeline.export_for_webapp \
--                              --ticker AAPL --push-to-supabase --dry-run
--      Confirms all columns/tables are reachable before any real writes.
-- ----------------------------------------------------------------------------
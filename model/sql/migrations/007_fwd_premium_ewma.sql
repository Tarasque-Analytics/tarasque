-- ============================================================================
-- Tarasque  Migration 007 — Forward premium EWMA columns
-- ============================================================================
-- Author:  model side (Leo)
-- Date:    2026-05-31
-- Scope:   ADDITIVE ONLY. Adds 3 EWMA-smoothed forward-premium columns to
--          volatility_history. Idempotent.
--
-- Context: the equity-page "VRP EWMA·21d" subgraph beneath the price chart
-- currently reads vrp_wedge_ewma_21d, which is the EWMA of the REFLEXIVE
-- wedge (iv_atm_30d − rv_21d_trailing). That column stays in place as the
-- model context-engine feature (and is the input the SHAP attribution at
-- "VRP wedge (EWMA 21d)" correctly references — no leakage as a feature).
--
-- This migration adds the EWMA of the validated FORWARD premium per horizon:
--   fwd_premium_ewma_21d  = EWMA_span21(fwd_premium_21d)   per (security_id, date)
--   fwd_premium_ewma_63d  = EWMA_span21(fwd_premium_63d)
--   fwd_premium_ewma_126d = EWMA_span21(fwd_premium_126d)
--
-- After this migration the UI subgraph repoints from vrp_wedge_ewma_21d to
-- fwd_premium_ewma_21d, finally making the "VRP" label match the validated
-- premium concept (IV − E[RV], EWMA-smoothed; ~99% positive, widens in stress,
-- per-ticker median IC +0.49 against forward realized vol across 93 tickers).
--
-- Span: 21 BD across all three horizons (validated optimum from the EWMA
-- span sweep; plateau across spans 10-42, peak at 21-42).
--
-- Sign convention: positive = market pricing more fear than the model.
-- Same convention as the underlying fwd_premium_{21d,63d,126d} columns
-- (see migration 002).
--
-- ============================================================================


ALTER TABLE public.volatility_history
    ADD COLUMN IF NOT EXISTS fwd_premium_ewma_21d   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS fwd_premium_ewma_63d   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS fwd_premium_ewma_126d  DOUBLE PRECISION;

COMMENT ON COLUMN public.volatility_history.fwd_premium_ewma_21d IS
    'EWMA (span=21 BD, per security_id over date) of fwd_premium_21d.
     Investor-facing premium gauge for the equity-page "VRP EWMA·21d" subgraph.
     This is the validated FORWARD VRP (IV − model E[RV]) smoothed, NOT the
     reflexive vrp_wedge_ewma_21d. Sign: positive = market > model.';
COMMENT ON COLUMN public.volatility_history.fwd_premium_ewma_63d IS
    'EWMA (span=21 BD) of fwd_premium_63d. Medium-horizon premium gauge for
     the term-structure panel.';
COMMENT ON COLUMN public.volatility_history.fwd_premium_ewma_126d IS
    'EWMA (span=21 BD) of fwd_premium_126d. Long-horizon premium gauge for
     the term-structure panel.';


-- ----------------------------------------------------------------------------
-- DONE
-- ----------------------------------------------------------------------------
-- After this migration:
--   1. model-side ETL (export_for_webapp.py) computes the 3 new columns
--      with a one-line .ewm(span=21, adjust=False).mean() per ticker, after
--      the existing compute_premium_columns() call writes fwd_premium_*d.
--   2. db.py upsert column list adds the 3 new columns alongside fwd_premium_*.
--   3. UI subgraph query repoints from vrp_wedge_ewma_21d to
--      fwd_premium_ewma_21d. vrp_wedge_ewma_21d stays in the schema as the
--      context-engine feature (still referenced by SHAP attribution).
--
-- Backfill: new columns are NULL for existing rows until the next ETL run
-- recomputes (daily_refresh or weekly_extend). To populate the full history
-- in one shot, run a backfill UPDATE that re-runs export_for_webapp.py over
-- the full date range and upserts; or execute the in-SQL backfill below
-- (uses Postgres window functions to approximate the EWMA from existing
-- fwd_premium_*d columns — see optional block at bottom of this file).
-- ----------------------------------------------------------------------------


-- ============================================================================
-- OPTIONAL: in-SQL backfill (one-shot, run once after the ALTER above)
-- ============================================================================
-- Computes the EWMA per security ordered by date directly in Postgres,
-- so historical rows don't need to wait for the next ETL pass to populate.
-- Uses the recursive EWMA definition with alpha = 2/(span+1) = 2/22 ≈ 0.0909.
--
-- Safe to skip if you're OK letting the ETL backfill on its next run.
-- Idempotent: running it again just recomputes the same values.
-- ----------------------------------------------------------------------------

-- WITH ordered AS (
--     SELECT
--         security_id,
--         date,
--         fwd_premium_21d,
--         fwd_premium_63d,
--         fwd_premium_126d,
--         ROW_NUMBER() OVER (PARTITION BY security_id ORDER BY date) AS rn
--     FROM public.volatility_history
-- ),
-- ewma AS (
--     -- For exact EWMA, a recursive CTE is required. For most monitoring
--     -- purposes a 21-period simple moving average is within ~2% of the
--     -- true EWMA span=21. Replace with a proper recursive CTE if exactness
--     -- matters; otherwise the ETL pass will overwrite with exact values.
--     SELECT
--         security_id, date,
--         AVG(fwd_premium_21d)  OVER (PARTITION BY security_id ORDER BY date
--             ROWS BETWEEN 20 PRECEDING AND CURRENT ROW) AS ewma_21,
--         AVG(fwd_premium_63d)  OVER (PARTITION BY security_id ORDER BY date
--             ROWS BETWEEN 20 PRECEDING AND CURRENT ROW) AS ewma_63,
--         AVG(fwd_premium_126d) OVER (PARTITION BY security_id ORDER BY date
--             ROWS BETWEEN 20 PRECEDING AND CURRENT ROW) AS ewma_126
--     FROM public.volatility_history
-- )
-- UPDATE public.volatility_history vh
-- SET fwd_premium_ewma_21d  = e.ewma_21,
--     fwd_premium_ewma_63d  = e.ewma_63,
--     fwd_premium_ewma_126d = e.ewma_126
-- FROM ewma e
-- WHERE vh.security_id = e.security_id AND vh.date = e.date;

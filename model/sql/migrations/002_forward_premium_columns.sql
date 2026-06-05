-- ============================================================================
-- Tarasque  Migration 002 — Forward premium scalar columns
-- ============================================================================
-- Author:  model side (Leo)
-- Date:    2026-05-25
-- Scope:   ADDITIVE ONLY. Adds 5 forward-premium scalar columns to
--          volatility_history. Idempotent.
--
-- Context: the equity page renders a Forward Vol Forecast chart that
-- compares two splined curves — model E(RV) (PCHIP through pfv_cal_21,
-- pfv_cal_63, pfv_cal_126) and market IV (PCHIP through iv_atm_30d,
-- iv_atm_60d, iv_atm_91d, iv_atm_182d). The CHART itself is splined
-- client-side from the existing 7 anchor columns; no JSONB needed.
--
-- THIS migration adds 5 scalar columns the backend computes per row so
-- the equity-page side panel ("AT H=126D: Model σ̂, Implied σ, Wedge,
-- Ratio") works without round-tripping, and so cross-ticker SQL queries
-- can rank tickers by premium ("show all tickers with rising mid-term
-- isolated premium").
--
-- Sign convention: positive = market pricing more fear than the model.
--   wedge = IV − Model
--
-- ============================================================================


ALTER TABLE public.volatility_history
    ADD COLUMN IF NOT EXISTS fwd_premium_21d         DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS fwd_premium_63d         DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS fwd_premium_126d        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS fwd_premium_21_to_63d   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS fwd_premium_63_to_126d  DOUBLE PRECISION;

COMMENT ON COLUMN public.volatility_history.fwd_premium_21d IS
    'IV(21) − Model(21). Positive = market pricing more fear than the model.
     IV(21) is PCHIP-on-total-variance interpolation of the iv_atm_* anchors
     (clipped to anchor range at the 21d boundary until short-DTE IV lands).';
COMMENT ON COLUMN public.volatility_history.fwd_premium_63d IS
    'IV(63) − Model(63). Cumulative wedge at the medium horizon.';
COMMENT ON COLUMN public.volatility_history.fwd_premium_126d IS
    'IV(126) − Model(126). Cumulative wedge at the long horizon.';
COMMENT ON COLUMN public.volatility_history.fwd_premium_21_to_63d IS
    'Isolated forward-window wedge for [21d, 63d]. Computed via total-variance
     algebra: forward_var(t1,t2) = (T2·σ²(T2) − T1·σ²(T1)) / (T2−T1).
     Isolates what the market vs model price for the period BETWEEN two horizons,
     independent of the 0→T1 path.';
COMMENT ON COLUMN public.volatility_history.fwd_premium_63_to_126d IS
    'Isolated forward-window wedge for [63d, 126d]. Same methodology as above.';


-- ----------------------------------------------------------------------------
-- DONE
-- ----------------------------------------------------------------------------
-- After this migration, model-side ETL writes the 5 new columns alongside
-- the existing pfv_cal_* and iv_atm_* anchors. Frontend splines the 7 anchors
-- client-side (d3.curveMonotoneX) for the Forward Vol Forecast chart.
-- ----------------------------------------------------------------------------

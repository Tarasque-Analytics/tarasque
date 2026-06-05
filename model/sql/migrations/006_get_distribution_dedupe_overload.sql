-- ============================================================================
--  006_get_distribution_dedupe_overload.sql — collapse two get_distribution
--                                               overloads into one canonical
--                                               4-arg signature
-- ============================================================================
--  Background: 005 created a 3-arg version, but a 4-arg version
--  (with p_n_bins) already existed in the DB from earlier work. PostgREST
--  can't route a 3-arg client call when both overloads define defaults —
--  fails with PGRST203 'could not choose the best candidate function'.
--
--  Fix: drop BOTH, recreate a single 4-arg function with p_n_bins defaulting
--  to 30. Frontend can pass any of 1–4 args (security_id is the only
--  required one); PostgREST has exactly one candidate to choose from.
--
--  Apply: paste into Supabase SQL editor, run.
--  Verify: SELECT proname, pg_get_function_identity_arguments(oid)
--          FROM pg_proc WHERE proname = 'get_distribution';
--          → should show exactly ONE row.
-- ============================================================================

-- Drop every overload, regardless of signature.
DROP FUNCTION IF EXISTS public.get_distribution(BIGINT, TEXT, INT);
DROP FUNCTION IF EXISTS public.get_distribution(BIGINT, TEXT, INT, INT);

CREATE OR REPLACE FUNCTION public.get_distribution(
    p_security_id    BIGINT,
    p_metric         TEXT,
    p_lookback_days  INT DEFAULT 1260,
    p_n_bins         INT DEFAULT 30
) RETURNS TABLE (
    scope               TEXT,
    bin_low             DOUBLE PRECISION,
    bin_high            DOUBLE PRECISION,
    count               INTEGER,
    current_value       DOUBLE PRECISION,
    current_percentile  DOUBLE PRECISION
)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    allowed_metrics TEXT[] := ARRAY[
        'rv', 'ewma_vol',
        'iv_atm_30d', 'iv_atm_60d', 'iv_atm_91d', 'iv_atm_182d',
        'vrp_wedge', 'vrp_wedge_ewma_21d',
        'pfv_21', 'pfv_63', 'pfv_126',
        'pfv_cal_21', 'pfv_cal_63', 'pfv_cal_126',
        'pfv_q15_21', 'pfv_q15_63', 'pfv_q15_126',
        'fwd_premium_21d', 'fwd_premium_63d', 'fwd_premium_126d',
        'fwd_premium_21_to_63d', 'fwd_premium_63_to_126d'
    ];
    cutoff_date DATE;
    sector_name TEXT;
    cur_val     DOUBLE PRECISION;
BEGIN
    IF NOT (p_metric = ANY(allowed_metrics)) THEN
        RAISE EXCEPTION 'get_distribution: metric % is not in the whitelist', p_metric
            USING HINT = 'See volatility_history columns in SUPABASE_SCHEMA.md §4.2';
    END IF;

    IF p_n_bins IS NULL OR p_n_bins < 1 OR p_n_bins > 200 THEN
        RAISE EXCEPTION 'get_distribution: p_n_bins must be between 1 and 200, got %', p_n_bins;
    END IF;

    cutoff_date := (CURRENT_DATE - (p_lookback_days || ' days')::INTERVAL)::DATE;

    SELECT s.gics_sector INTO sector_name
    FROM securities s
    WHERE s.security_id = p_security_id;

    EXECUTE format(
        'SELECT %1$I FROM volatility_history
         WHERE security_id = $1 AND %1$I IS NOT NULL
         ORDER BY date DESC LIMIT 1',
        p_metric
    ) INTO cur_val USING p_security_id;

    RETURN QUERY EXECUTE format($q$
        WITH stock_vals AS (
            SELECT %1$I::DOUBLE PRECISION AS v
            FROM volatility_history
            WHERE security_id = $1
              AND date >= $2
              AND %1$I IS NOT NULL
        ),
        sector_vals AS (
            SELECT v.%1$I::DOUBLE PRECISION AS v
            FROM volatility_history v
            JOIN securities s ON s.security_id = v.security_id
            WHERE s.gics_sector = $3
              AND v.date >= $2
              AND v.%1$I IS NOT NULL
        ),
        market_vals AS (
            SELECT %1$I::DOUBLE PRECISION AS v
            FROM volatility_history
            WHERE date >= $2
              AND %1$I IS NOT NULL
        ),
        scoped AS (
            SELECT 'stock'::TEXT  AS scope, v FROM stock_vals
            UNION ALL
            SELECT 'sector'::TEXT, v FROM sector_vals
            UNION ALL
            SELECT 'market'::TEXT, v FROM market_vals
        ),
        scope_stats AS (
            SELECT
                scope,
                MIN(v) AS lo,
                MAX(v) AS hi,
                COUNT(*) AS n,
                GREATEST((MAX(v) - MIN(v)) / $4::DOUBLE PRECISION, 1e-12) AS step
            FROM scoped
            GROUP BY scope
        ),
        binned AS (
            SELECT
                s.scope,
                LEAST(
                    width_bucket(s.v, st.lo, st.hi + st.step * 1e-6, $4),
                    $4
                ) AS bin_idx,
                st.lo,
                st.step
            FROM scoped s
            JOIN scope_stats st USING (scope)
            WHERE st.n > 0
        ),
        bin_counts AS (
            SELECT
                scope,
                bin_idx,
                MIN(lo)   AS lo,
                MIN(step) AS step,
                COUNT(*)::INTEGER AS bcount
            FROM binned
            GROUP BY scope, bin_idx
        ),
        percentiles AS (
            SELECT
                scope,
                100.0 * SUM(CASE WHEN v <= $5 THEN 1 ELSE 0 END)::DOUBLE PRECISION
                       / NULLIF(COUNT(*), 0) AS pct
            FROM scoped
            GROUP BY scope
        )
        SELECT
            b.scope,
            (b.lo + (b.bin_idx - 1) * b.step)::DOUBLE PRECISION AS bin_low,
            (b.lo +  b.bin_idx      * b.step)::DOUBLE PRECISION AS bin_high,
            b.bcount AS count,
            $5::DOUBLE PRECISION AS current_value,
            p.pct AS current_percentile
        FROM bin_counts b
        LEFT JOIN percentiles p USING (scope)
        ORDER BY b.scope, b.bin_idx;
    $q$, p_metric)
    USING p_security_id, cutoff_date, sector_name, p_n_bins, cur_val;
END;
$$;

COMMENT ON FUNCTION public.get_distribution(BIGINT, TEXT, INT, INT) IS
    'Returns N-bin histograms (default 30) over stock/sector/market scopes for
     a whitelisted metric in volatility_history. current_value and
     current_percentile are repeated per scope so the frontend can render the
     dashed "you are here" line without a second query. See
     model/SUPABASE_SCHEMA.md §4.10.';

GRANT EXECUTE ON FUNCTION public.get_distribution(BIGINT, TEXT, INT, INT)
    TO anon, authenticated;

-- ============================================================================
--  005_get_distribution_rpc.sql — implement get_distribution()
-- ============================================================================
--  Replaces the stub from 001 with a real implementation.
--
--  Returns 30-bin histograms × 3 scopes (stock / sector / market) for a
--  whitelisted metric over a configurable lookback window. The current value
--  + its percentile within each scope are repeated on every row of that scope
--  so the frontend can render the "where we are now" dashed line in a single
--  pass without a second query.
--
--  Apply: paste into Supabase SQL editor and run.
--  Verify: SELECT * FROM get_distribution(320193, 'rv') LIMIT 5;
--          (320193 = AAPL's security_id under the lead-dev CIK convention)
-- ============================================================================

DROP FUNCTION IF EXISTS public.get_distribution(BIGINT, TEXT, INT);

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
STABLE
AS $$
DECLARE
    n_bins      CONSTANT INT := 30;
    -- Whitelist: must match real columns in volatility_history. Reject anything
    -- else with a clear error rather than letting dynamic SQL leak an attack.
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

    cutoff_date := (CURRENT_DATE - (p_lookback_days || ' days')::INTERVAL)::DATE;

    SELECT s.gics_sector INTO sector_name
    FROM securities s
    WHERE s.security_id = p_security_id;

    -- Latest non-null value for this security (current dotted-line value)
    EXECUTE format(
        'SELECT %1$I FROM volatility_history
         WHERE security_id = $1 AND %1$I IS NOT NULL
         ORDER BY date DESC LIMIT 1',
        p_metric
    ) INTO cur_val USING p_security_id;

    -- Three scoped value sets → bin per scope using each scope's own MIN/MAX.
    -- width_bucket(value, lo, hi, n) returns 1..n inside [lo,hi); we nudge hi
    -- by a tiny epsilon so the max value lands in bin n instead of bin n+1.
    -- Bins with zero observations are simply absent from the result.
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
                -- step protects against lo == hi (all values equal); without
                -- this guard width_bucket would divide by zero.
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
    USING p_security_id, cutoff_date, sector_name, n_bins, cur_val;
END;
$$;

COMMENT ON FUNCTION public.get_distribution(BIGINT, TEXT, INT) IS
    'Returns 30-bin histograms over stock/sector/market scopes for a whitelisted
     metric in volatility_history. current_value and current_percentile are
     repeated per scope so the frontend can render the dashed "you are here"
     line without a second query. See model/SUPABASE_SCHEMA.md §4.10.';

-- Frontend reads via the anon role through PostgREST. Service-role writes
-- don't need an explicit grant (bypasses RLS), but reads do.
GRANT EXECUTE ON FUNCTION public.get_distribution(BIGINT, TEXT, INT)
    TO anon, authenticated;

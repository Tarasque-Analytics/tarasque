-- pipeline_runs — OPTIONAL observability ledger for the automation pipeline (PLAN §3.3).
--
-- ⚠ PROPOSAL ONLY — NOT APPLIED. This scaffold ships no migration. Adopt by copying into
-- supabase/migrations/ (and mirror in database_SQL_defs.sql) once the run-ledger decision is made.
--
-- This table is for observability/audit/alerting ONLY. It is NEVER the source of truth for
-- freshness/incrementality — that is always derived from the data tables (PLAN §3.1). If the ledger
-- and the data tables disagree, the data tables win.

create table if not exists public.pipeline_runs (
  id           bigint generated always as identity primary key,
  run_date     date        not null,
  stage        text        not null,   -- 'ensure_universe' | 'fetch_prices' | 'fetch_options'
                                        -- | 'run_model' | 'upload_outputs' | 'ai_overviews'
  status       text        not null,   -- 'success' | 'partial' | 'failed' | 'skipped'
  started_at   timestamptz not null default now(),
  finished_at  timestamptz,
  rows_written integer,
  n_securities integer,
  n_skipped    integer,
  n_failed     integer,
  error        text,
  meta         jsonb,                  -- per-stage extras: provider, model_version, cost estimate
  constraint pipeline_runs_run_stage_unique unique (run_date, stage)  -- one row/stage/day; upsert on rerun
);

create index if not exists idx_pipeline_runs_run_date
  on public.pipeline_runs using btree (run_date desc);

-- NOTE (backend/CLAUDE.md RLS gotcha): if the app ever reads this table through the Data API
-- (e.g. a "last successful run" status widget), it needs a permissive SELECT policy for anon, else
-- PostgREST returns 0 rows silently. The service-role write client bypasses RLS, so writes are fine.
--
-- create policy "Enable read access for all users" on public.pipeline_runs for select using (true);

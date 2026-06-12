-- remap_security_ids_cik.sql
-- ONE-OFF data migration: remap securities.security_id -> SEC CIK, cascading to all child tables.
-- Generated from SEC company_tickers.json + the hosted securities table. 93 tickers.
--
-- HOW TO RUN: paste into the Supabase SQL editor for project kynrztmoshssqduxhdsb and run.
--   TAKE A BACKUP FIRST (Dashboard -> Database -> Backups, or pg_dump).
-- This is NOT a supabase/migrations file on purpose: it is a one-off keyed to the HOSTED data,
-- and would mis-apply against the local seed (different ids). Kept in automation/sql/ for the record.
--
-- Safety: runs in a single transaction with guards (FK-cascade check, mapping completeness,
-- collision check). Any failure raises and rolls back the whole thing — no partial remap.
-- All 6 child FKs are ON UPDATE CASCADE, so updating securities.security_id rewrites child rows
-- automatically. Counts are preserved (UPDATE, not delete/insert).

begin;

-- 0) Guard: every FK referencing securities must be ON UPDATE CASCADE, or abort.
do $$
declare bad text;
begin
  select string_agg(conname, ', ') into bad
  from pg_constraint
  where contype = 'f' and confrelid = 'public.securities'::regclass and confupdtype <> 'c';
  if bad is not null then
    raise exception 'Aborting: FK(s) not ON UPDATE CASCADE: %', bad;
  end if;
end $$;

-- 1) ticker -> CIK mapping (from SEC company_tickers.json)
create temporary table tmp_id_map (ticker text primary key, cik bigint not null) on commit drop;
insert into tmp_id_map (ticker, cik) values
  ('AAPL', 320193),
  ('ABBV', 1551152),
  ('ABT', 1800),
  ('ADBE', 796343),
  ('AEP', 4904),
  ('AMAT', 6951),
  ('AMD', 2488),
  ('AMGN', 318154),
  ('AMT', 1053507),
  ('AMZN', 1018724),
  ('APD', 2969),
  ('AVGO', 1730168),
  ('AXP', 4962),
  ('BA', 12927),
  ('BAC', 70858),
  ('BKNG', 1075531),
  ('BLK', 2012383),
  ('BMY', 14272),
  ('C', 831001),
  ('CAT', 18230),
  ('CCI', 1051470),
  ('CL', 21665),
  ('CMCSA', 1166691),
  ('COP', 1163165),
  ('COST', 909832),
  ('CRM', 1108524),
  ('CSCO', 858877),
  ('CVS', 64803),
  ('CVX', 93410),
  ('D', 715957),
  ('DE', 315189),
  ('DIS', 1744489),
  ('DOW', 1751788),
  ('DUK', 1326160),
  ('EOG', 821189),
  ('EQIX', 1101239),
  ('F', 37996),
  ('FCX', 831259),
  ('FDX', 1048911),
  ('GE', 40545),
  ('GILD', 882095),
  ('GM', 1467858),
  ('GOOGL', 1652044),
  ('GS', 886982),
  ('HD', 354950),
  ('HON', 773840),
  ('IBM', 51143),
  ('INTC', 50863),
  ('JNJ', 200406),
  ('JPM', 19617),
  ('KO', 21344),
  ('LLY', 59478),
  ('LMT', 936468),
  ('LOW', 60667),
  ('MCD', 63908),
  ('MMM', 66740),
  ('MO', 764180),
  ('MPC', 1510295),
  ('MRK', 310158),
  ('MS', 895421),
  ('MSFT', 789019),
  ('MU', 723125),
  ('NEE', 753308),
  ('NEM', 1164727),
  ('NFLX', 1065280),
  ('NKE', 320187),
  ('NOC', 1133421),
  ('NVDA', 1045810),
  ('ORCL', 1341439),
  ('PEP', 77476),
  ('PFE', 78003),
  ('PG', 80424),
  ('PLD', 1045609),
  ('PM', 1413329),
  ('PSX', 1534701),
  ('QCOM', 804328),
  ('RTX', 101829),
  ('SBUX', 829224),
  ('SCHW', 316709),
  ('SLB', 87347),
  ('SO', 92122),
  ('SPG', 1063761),
  ('T', 732717),
  ('TGT', 27419),
  ('TMO', 97745),
  ('TSLA', 1318605),
  ('TXN', 97476),
  ('UNH', 731766),
  ('UPS', 1090727),
  ('USB', 36104),
  ('WFC', 72971),
  ('WMT', 104169),
  ('XOM', 34088);

-- 2) Guard: every non-blank ticker in securities must have a mapping.
do $$
declare missing text;
begin
  select string_agg(s.ticker, ', ') into missing
  from securities s
  where coalesce(s.ticker,'') <> ''
    and not exists (select 1 from tmp_id_map m where m.ticker = s.ticker);
  if missing is not null then
    raise exception 'Aborting: no CIK mapping for: %', missing;
  end if;
end $$;

-- 3) Guard: no target CIK may equal a DIFFERENT security's current id (transient-collision safety).
do $$
declare bad text;
begin
  select string_agg(m.ticker, ', ') into bad
  from tmp_id_map m
  join securities s on s.security_id = m.cik and s.ticker <> m.ticker;
  if bad is not null then
    raise exception 'Aborting: CIK collides with an existing different id for: %', bad;
  end if;
end $$;

-- 4) The remap (cascades to prices_history, options_chain, volatility_history,
--    shap_snapshot, ai_overview, event_history via ON UPDATE CASCADE).
update securities s
set security_id = m.cik
from tmp_id_map m
where s.ticker = m.ticker and s.security_id <> m.cik;

-- 5) Junk blank-ticker row (id=67). It HAS 1 orphan prices_history row. Default here is
--    NON-DESTRUCTIVE: deactivate it (keeps the row + its price). To hard-delete it (which ALSO
--    removes its 1 prices_history row via ON DELETE CASCADE), uncomment the delete and remove the
--    update — and adjust the post-run prices_history count to 283796.
update securities
set active = false, excluded_reason = 'blank ticker (pre-CIK junk row)'
where security_id = 67 and coalesce(ticker,'') = '';
-- delete from securities where security_id = 67 and coalesce(ticker,'') = '';  -- opt-in hard delete (-1 price row)

-- 6) Verify: securities now keyed on CIK; spot-check a few.
select ticker, security_id from securities order by ticker limit 10;

-- PREVIEW vs APPLY: the Supabase SQL editor auto-commits each run, so to do a safe dry run first,
-- temporarily change the line below to `rollback;` and run — the section-6 SELECT shows the
-- would-be result and NOTHING is saved (guards still fire). Then switch it back to `commit;` to apply.
commit;

-- Post-run sanity (run separately after commit):
--   select count(*) from prices_history;       -- expect 283797
--   select count(*) from volatility_history;   -- expect 283796
--   select count(*) from event_history;        -- expect 6948
--   select security_id from securities where ticker = 'AAPL';  -- expect 320193

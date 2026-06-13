# Backend — Volarbear API

FastAPI + Uvicorn service that serves per-equity volatility data to the frontend. This file
covers the **backend only**; the frontend app and the model have their own context files
(`model/claude_context.md` is maintained by a different developer — don't assume it tracks
backend changes).

## Layout

- `main.py` — FastAPI app, routes, CORS, lifespan (Supabase client init).
- `database.py` — all Supabase query helpers. The global `supabase` client is injected by
  `main.py`'s lifespan via `initialize_db(client)`.
- `BACKEND_GUIDE.md` — setup/run/troubleshooting reference.

## Running

**Requires Python >= 3.10** (`python-dotenv` 1.2.x needs 3.10+). On 3.8/3.9, pip reports a
misleading `Could not find a version that satisfies the requirement python-dotenv==1.2.2` — that
is a Python-version mismatch (pip filters out the incompatible release), **not** a missing/typo'd
version. Use a 3.10+ interpreter (e.g. `py -3.11 -m pip install ...`).

```bash
pip install -r backend/requirements.txt          # needs the `supabase` SDK (NOT `supabase-py`)
python -m backend.main                            # run from the repo root; serves :8000, API base /api
```

**Launch as a module from the repo root** (`python -m backend.main` or
`uvicorn backend.main:app`). `python backend/main.py` does **not** work — the code uses absolute
`from backend import ...` imports, which require the repo root on `sys.path`.

Env vars load from a `.env` at the repo root (parent of `backend/`):
`VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`. The lifespan handler raises if either
is missing, and `await`s `acreate_client(...)` (it's async — must be awaited). CORS is open to
`http://localhost:5173` and `http://localhost:3000`.

## Environments & configuration (dev / stg / prod)

Three target environments, selected **per-process at startup** — no runtime switching. Changing
environment means a restart, which is not expected/encouraged mid-session during development.

- **dev** — local. Backend + Vite run locally against the **local Supabase stack**
  (`npx supabase start`; API `http://127.0.0.1:54321`, local publishable key). Default for daily dev.
- **stg** — remote. Backend + Vite still run locally but point at the **hosted Supabase** project
  (shared/real data) to validate against production-like data before deploying.
- **prod** — deployed. Hosted Supabase + deployed backend/frontend. Not touched during development.

What actually varies per environment:
- Backend → which Supabase it connects to (`VITE_SUPABASE_URL` / `VITE_SUPABASE_PUBLISHABLE_KEY`).
- Frontend → the FastAPI base URL (currently **hardcoded** `http://localhost:8000/api` in
  `app/utils/database.ts` and `app/utils/tickers.ts` — must become env-driven for stg/prod).
- *Not* "DB connection strings": the app uses the Supabase **API URL + anon/publishable key**, not
  a raw Postgres string (the `:54322` URL is for the CLI/migrations only).

**Intended selection mechanism (planned — not yet implemented; see Deployment next steps):**
- Frontend: Vite `--mode` + mode env files (`.env.development` / `.env.staging` / `.env.production`)
  read via `import.meta.env`, extending the team's existing Vite-mode pattern.
- Backend: mirror with an `APP_ENV` (`dev|stg|prod`) var selecting the Supabase target; defaults to
  `dev`/local so local dev needs zero setup.

**Today (pre-deploy):** only a single repo-root `.env` exists. To switch local↔remote, edit
`VITE_SUPABASE_URL` / `VITE_SUPABASE_PUBLISHABLE_KEY` and **restart both** the backend and Vite
(both read env only at startup). Remote keys are secrets (never commit); local-stack keys are
shared non-secret defaults.

## Data sources

- DB endpoint `/api/equity/{symbol}` resolves the ticker to a `security_id` via `securities`,
  then aggregates Supabase queries (in `database.py`) in parallel via `asyncio.gather`.
  `price_history` returns the **full available history** (paginated through the per-request row
  cap; some securities go back ~12 years) so the chart's range selector works at every range.
  `events` likewise returns the security's full `event_history` (sparse, so a single request); the
  frontend windows both to the selected range. `security` is curated metadata (company name, GICS
  sector/industry) pulled from the `securities` row already fetched to resolve `security_id`.
  Current payload keys: `symbol, security, volatility_history,
  price_history, options_chain, ai_overview,
  latest_shap_snapshot, events`. **`distribution_data` is temporarily disabled** (see below).
- `/api/equities` returns the list of active ticker symbols (`securities.active`, via
  `get_active_tickers()` in `database.py`) and feeds the frontend ticker search. It replaced the
  legacy filesystem-scan `/api/tickers*` endpoints, removed in the file-data cleanup (issue #83).
- `/api/dashboard`, `/api/sector/{sector}`, `/api/macro` are unimplemented stubs returning `{}`.

Because the equity queries run under one `asyncio.gather`, any single query raising will fail
the whole payload (no partial results).

## Database

Canonical schema: `supabase/database_SQL_defs.sql`; migrations in `supabase/migrations/`.
**Keep `database.py` query column/table names in sync with the defs file — it's authoritative.**
`securities.security_id` is the join key for nearly every table (FKs cascade on delete).

Tables: `securities`, `prices_history`, `volatility_history`, `options_chain`,
`shap_snapshot`, `model_runs`, `ai_overview`, `event_history`, `macro_calendar`.

### Local stack & migrations

`database_SQL_defs.sql` is a reference dump of the **hosted** schema (authoritative for
table/column names). The local DB is built from `supabase/migrations/` — a single
`20260310003634_initial_schema.sql` that now **mirrors the hosted schema** (it had drifted —
old `events_history` shape, no `macro_calendar` — which broke seeding until reconciled).
Local workflow (Docker must be running):

```bash
npx supabase start      # boots the local stack (API :54321, DB :54322)
npx supabase db reset   # drops, re-applies migrations, then runs supabase/seed.sql
```

`seed.sql` is **local-only** sample data — it is not run against the hosted DB. If the hosted
schema changes, update the migration to match (or regenerate via `supabase db pull` once the
project is linked; that also captures RLS/grants/functions the defs dump omits).

### RLS / Data API reads — gotcha

Tables served through the Supabase **Data API** are read with the **publishable/anon key**, so
each needs a permissive `SELECT` RLS policy for `anon`. If RLS is enabled with **no policy**,
PostgREST returns **0 rows silently** (no error) — the data is there, the API just can't see it.
This bit us: `event_history` (and `macro_calendar`, `model_runs`) had RLS on with no policy, so
`/api/equity/:symbol` returned an empty `events` array even though rows existed (they show in the
dashboard, which runs as `service_role` and bypasses RLS). Fix is a read policy mirroring the
already-readable tables:

```sql
create policy "Enable read access for all users" on public.event_history for select using (true);
```

The hosted fix was applied via the dashboard, so it is **not** in `database_SQL_defs.sql` (the
dump omits RLS/grants) nor in the local migration — the local stack won't match until a
`supabase db pull` or an explicit policy migration captures it. Add the same policy for
`macro_calendar` / `model_runs` when an endpoint starts reading them.

### Event model — important distinction

Two separate event sources; do not conflate them:

- **`event_history`** is **per-security**. Every row has a `security_id` (NOT NULL, part of the
  PK) describing an event specific to that one security. Query it filtered by `security_id`.
  Columns: `security_id, event_id, event_date, title, description, event_type, scope, source`.
  It has **no** `scope_value` or `severity` column — do not reference those.

- **`macro_calendar`** handles **market-wide events that affect all securities** (e.g. CPI,
  FOMC, NFP). Not tied to any `security_id`. PK `(date, event_type)`, with `days_to_event` /
  `event_date`. Use this for anything cross-security; never model market/sector-wide events
  inside `event_history`.

### Other schema notes

- `ai_overview`: order by `generated_at` (the timestamp column — there is no `date` column).
  Latest row per `(security_id, model_ver, prompt_ver)` where `flagged = false`.
- `volatility_history` is the wide feature table (RV/IV, VRP wedge, `pfv_*` and `fwd_premium_*`
  term-structure features, cached SHAP top-10 JSONB per horizon 21/63/126).
- `get_distribution` is a Postgres RPC (stored procedure), **not** a table — it is not in
  `database_SQL_defs.sql`. **Currently commented out** in both `main.py` and `database.py`
  (grep `distribution PR`): the RPC hits a Postgres statement timeout (code `57014`), so it was
  disabled to keep `/api/equity` working. Re-enabling is deferred to a separate PR pending
  finance-side input on the distribution structure — see the tracking GitHub issue.

## Conventions

- Ticker symbols are normalized to uppercase at the API boundary.
- DB helpers raise `HTTPException` on query failure and print a `flush=True` diagnostic.
  - **Log the raw exception server-side, return a generic client `detail`.** The `flush=True`
    `print(f"Exception at <fn>: {e}")` is the server-side log; the `HTTPException` `detail`
    returned to the caller must **not** interpolate `{e}` — doing so leaks internal
    Supabase/PostgREST error text and schema details to API clients (flagged in review on
    `get_latest_model_run`). Pattern: `detail="Error fetching from <table> table"` (no `: {e}`).
  - **Known debt:** the other helpers in `database.py` (`get_security_data`,
    `get_volatility_history`, `get_price_history`, `get_options_chain`, `get_ai_overview`,
    `get_shap_snapshot`, `get_events`) still echo `{e}` in their `detail`. **Don't do a sweeping
    fix** — there are open PRs modifying `database.py`, and a file-wide edit would collide with
    them. Instead, drop `: {e}` from each helper's `detail` (keep the server-side `print`)
    opportunistically, in whatever PR/call is already touching that helper.
- `/api/equity/{symbol}` re-raises `HTTPException` as-is to preserve status codes.

## Testing

Tests live in `backend/tests/` (pytest). Config is `pytest.ini` at the repo root
(`pythonpath = .` so `import backend` resolves; `testpaths = backend/tests`).

```bash
pip install -r backend/requirements-dev.txt   # installs pytest
python -m pytest                               # from the repo root
npm run test:backend                           # same thing, via package.json
```

`test_db_connection.py` guards the **database connection and client wiring**, not the schema —
it deliberately asserts nothing about table columns or row contents (so schema changes don't
break it). It catches regressions like the unawaited-`acreate_client` lifespan bug. Two tiers:

- **Offline** (always run): `acreate_client` is a coroutine that must be awaited and returns an
  `AsyncClient`; `initialize_db` wires the client into the module global.
- **Live** (skipped unless `VITE_SUPABASE_URL` + `VITE_SUPABASE_PUBLISHABLE_KEY` are set in the
  repo-root `.env`, which `conftest.py` loads): lifespan boots and `/api/health` responds; the
  post-startup client is a real `AsyncClient`; a query round-trips and returns a list. Note: the
  live tests **skip** (not fail) without creds, so CI without Supabase secrets won't enforce them.

When adding connection tests, keep them schema-agnostic. The live tests drive the `lifespan` +
ASGI app via `httpx.ASGITransport` rather than Starlette's `TestClient` (this env's `starlette`
is incompatible with `httpx >= 0.28`, which removed the `app=` kwarg).

## Deployment — next steps (after this PR merges)

This PR's scope is the **database connection**, not deployment: the local migration now mirrors
the hosted schema, `supabase db reset` + seed runs clean, `/api/equity/:symbol` hits the DB, and
the frontend loads the payload into React context. Nothing is deployed yet, by design. The PR is
still open. After it merges:

1. **Implement the dev/stg/prod config** (the mechanism in *Environments* above):
   - `app/config.ts` reading `import.meta.env` → `API_BASE_URL` + Supabase URL/key; replace the
     two hardcoded `API_BASE_URL` constants in `app/utils/database.ts` and `app/utils/tickers.ts`.
   - `.env.development` (local stack — committable) + `.env.staging` / `.env.production`
     (hosted — secrets supplied by the platform, not committed).
   - `backend/config.py` reading `APP_ENV` (`dev|stg|prod`) → Supabase URL/key.
2. **Choose hosting** (backend e.g. Render/Fly/Railway; frontend e.g. Vercel/Netlify), set the
   stg/prod `API_BASE_URL`, and update backend CORS (`main.py`, currently localhost-only) to allow
   the deployed frontend origin(s).
3. **Link Supabase** (`supabase link`) and reconcile remaining local↔hosted drift via
   `supabase db pull` (RLS, grants, the real `get_distribution` body — none of which are in
   `database_SQL_defs.sql`).
4. **Set platform env vars** per deploy target (`APP_ENV`, Supabase URL/key); never commit hosted secrets.
5. **Re-enable `get_distribution`** (its own tracking issue) before prod relies on distributions.

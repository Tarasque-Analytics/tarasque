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

```bash
python backend/main.py    # serves http://127.0.0.1:8000, API base /api
```

Env vars load from a `.env` at the repo root (parent of `backend/`):
`VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`. The lifespan handler raises if either
is missing. CORS is open to `http://localhost:5173` and `http://localhost:3000`.

## Data sources (mid-migration)

- Legacy file endpoints (`/api/tickers`, `/api/tickers/{symbol}`) read
  `app/assets/data/{SYMBOL}_Payload.json`.
- DB endpoint `/api/equity/{symbol}` aggregates Supabase queries (in `database.py`) in parallel
  via `asyncio.gather`.

## Database

Canonical schema: `supabase/database_SQL_defs.sql`; migrations in `supabase/migrations/`.
**Keep `database.py` query column/table names in sync with the defs file — it's authoritative.**
`securities.security_id` is the join key for nearly every table (FKs cascade on delete).

Tables: `securities`, `prices_history`, `volatility_history`, `options_chain`,
`shap_snapshot`, `model_runs`, `ai_overview`, `event_history`, `macro_calendar`.

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
  `database_SQL_defs.sql`. Called via `supabase.rpc("get_distribution", ...)`.

## Conventions

- Ticker symbols are normalized to uppercase at the API boundary.
- DB helpers raise `HTTPException` on query failure and print a `flush=True` diagnostic.
- `/api/equity/{symbol}` re-raises `HTTPException` as-is to preserve status codes.

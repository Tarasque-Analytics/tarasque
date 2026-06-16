# Tech Stack Overview

A high-level map of the technologies used across **volarbmodel**, split by the three
app-team components: the **frontend app**, the **backend API**, and the **automation**
data tooling. They share one Supabase (Postgres) database.

> The quant **`model/`** pipeline is owned by a separate team and is intentionally out of
> scope here. This document covers only the app, backend, and automation tracks.

## At a glance

| Component | Language | Core framework | Talks to the DB as | Purpose |
|---|---|---|---|---|
| `app/` (frontend) | TypeScript | React 19 + React Router 7 (SSR) | — (via backend API; Supabase only for auth) | UI for volatility / equity analysis |
| `backend/` (API) | Python 3.10+ | FastAPI + Uvicorn | **read-only** (anon/publishable key) | Serves per-equity data to the frontend |
| `automation/` (tooling) | Python | CLI scripts (no web framework) | **write** (secret key, bypasses RLS) | Imports market data into the DB |
| Shared data layer | SQL | Supabase (Postgres) | — | Single source of truth for app data |

Data flow: **automation writes → Supabase → backend reads → frontend renders.**

---

## Frontend (`app/`)

A server-side-rendered React app served through React Router 7 in framework mode.

- **Language:** TypeScript 5.9
- **UI framework:** React 19
- **Routing / SSR:** React Router 7 (framework mode, SSR enabled) — file-based routes in
  `app/routes.ts`; each `routes/<name>.tsx` co-locates a loader and re-exports its page from
  `app/pages/`.
- **Build tool / dev server:** Vite 7 (`@react-router/dev`), with `vite-tsconfig-paths`.
- **Styling:** Tailwind CSS 4 (`@tailwindcss/vite`); shared design tokens/primitives in
  `app/app.css`.
- **Charts:** Chart.js 4 via `react-chartjs-2`.
- **Auth:** `@supabase/supabase-js` (`app/supabaseClient.ts`) — used **only** for authentication
  (email/password + Google OAuth). The client-side session check lives in
  `app/layouts/ProtectedLayout.tsx`. All equity/business data flows through the backend API, not
  directly from the browser to Supabase.
- **Data fetching:** `app/utils/database.ts` is the single API client (`loadEquityData`,
  `loadEquityList`), calling the backend at `http://localhost:8000/api` (base URL currently
  hardcoded — slated to become env-driven for staging/prod).
- **Testing:** Vitest 4 with `@testing-library/react`, `@testing-library/jest-dom`, and `jsdom`
  (setup in `app/test/setup.ts`).
- **Server runtime (prod):** `@react-router/serve` (`@react-router/node`) serving the SSR bundle.

Run / build:

```bash
npm run dev          # frontend + backend together (concurrently)
npm run typecheck    # react-router typegen && tsc  (pre-PR gate)
npm run build        # SSR production bundle -> build/client + build/server
npm run start        # serve the built bundle
```

The primary working surface is **`/equity/:symbol`**, which is fully wired to live DB data via
the backend. `/dashboard`, `/sector/:sector`, and `/macro` are present but currently render
"coming soon" placeholders (no fabricated data ships).

---

## Backend (`backend/`)

A FastAPI service that aggregates Supabase queries into per-equity payloads for the frontend.

- **Language:** Python (requires **3.10+**, per `python-dotenv` 1.2.x).
- **Web framework:** FastAPI 0.104.1
- **ASGI server:** Uvicorn 0.24.0 (with `--reload` in dev)
- **DB client:** the official `supabase` Python SDK — the **async** client
  (`acreate_client`), initialized in the FastAPI `lifespan` handler and injected into
  `database.py`. Reads use the **publishable/anon key** (read-only under Postgres RLS).
- **Config:** `python-dotenv` loads a repo-root `.env` (`VITE_SUPABASE_URL`,
  `VITE_SUPABASE_PUBLISHABLE_KEY`); the app raises at startup if they're missing.
- **Form parsing:** `python-multipart`.
- **Testing:** `pytest` (`backend/requirements-dev.txt`), config in `pytest.ini`; tests in
  `backend/tests/` focus on DB connection/client wiring.

Architecture notes:
- `main.py` — app, routes, CORS (localhost origins), lifespan/Supabase init.
- `database.py` — all query helpers; per-equity queries run concurrently via `asyncio.gather`.
- Endpoints: `GET /api/health`, `GET /api/equities` (active ticker list),
  `GET /api/equity/{symbol}` (composite payload). `/api/dashboard`, `/api/sector/{sector}`,
  `/api/macro` are unimplemented stubs.

Run (from the repo root — it's a module):

```bash
pip install -r backend/requirements.txt
python -m backend.main          # or: uvicorn backend.main:app --port 8000
```

---

## Automation (`automation/`)

Standalone Python CLI tooling — the **only** component that writes to the database. No web
framework; invoked as modules from the repo root.

- **Language:** Python
- **DB client:** the `supabase` SDK using the **secret key** (`db.WriteClient`), which bypasses
  RLS for idempotent keyed upserts. Strictly separate from the backend's read client.
- **Market data:** `yfinance` (current-day options chains — free, no API key). Option greeks
  (delta) are computed **in-house** in `black_scholes.py` (`math.erf`; no SciPy needed).
- **Universe sync:** `requests` + `pandas` to build the S&P 500 / securities universe from the
  Wikipedia constituents table and SEC `company_tickers.json`.
- **Config:** `python-dotenv` (repo-root `.env`: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`,
  `AUTOMATION_ENV`).
- **Testing:** `pytest` (pure-function tests for `black_scholes` and `expiry_selection`).

Shipped tools:
- `tools/fetch_options.py` — imports options chains (yfinance → `options_chain`), over a reusable
  core (`options_import.py`, `providers/options_provider.py`, `expiry_selection.py`).
- `tools/sync_sp500.py` — syncs SEC CIK + S&P 500 + GICS metadata → `securities`.

```bash
pip install -r automation/requirements.txt
python -m automation.tools.fetch_options --tickers AAPL --dry-run   # no DB writes
python -m automation.tools.sync_sp500                                # preview universe sync
python -m pytest automation/tests
```

> The broader orchestrated nightly pipeline (price fetch, model run, output upload, AI overviews)
> is **designed but not yet implemented** — see `automation/CLAUDE.md`.

---

## Shared data layer — Supabase / Postgres

- **Database:** Supabase (managed Postgres) — the single source of truth for app data.
- **Access model:** Postgres **Row-Level Security (RLS)**. The backend reads with the
  anon/publishable key (needs permissive `SELECT` policies); automation writes with the secret
  key (bypasses RLS).
- **Schema & migrations:** managed via the Supabase CLI under `supabase/`
  (`migrations/`, `seed.sql` for local sample data, `config.toml`). `database_SQL_defs.sql` is the
  authoritative reference dump of the hosted schema.
- **Key tables:** `securities`, `prices_history`, `volatility_history`, `options_chain`,
  `shap_snapshot`, `model_runs`, `ai_overview`, `event_history`, `macro_calendar`.
  `securities.security_id` (the SEC CIK) is the join key across nearly every table.

---

## Tooling & infrastructure

- **Package management:** npm (frontend, `package.json` / `package-lock.json`); pip +
  `requirements.txt` per Python component.
- **Containerization:** multi-stage `Dockerfile` (Node 20 Alpine) builds and serves the SSR
  frontend.
- **Local orchestration:** `concurrently` runs the frontend and backend together via `npm run dev`.
- **Environments:** a single repo-root `.env` today; a planned `dev | stg | prod` split (Vite
  modes + backend `APP_ENV`) is documented in `backend/CLAUDE.md` but not yet implemented.

## Where to read more

- `README.md` — high-level app overview and quick start.
- `CONTRIBUTING.md` — app-developer workflows, run/build/deploy steps.
- `app/CLAUDE.md`, `backend/CLAUDE.md`, `automation/CLAUDE.md`, `backend/BACKEND_GUIDE.md` —
  detailed per-component context, conventions, and gotchas.

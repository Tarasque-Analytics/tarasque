# Backend Guide

This guide covers the current FastAPI backend used by the app team, including setup, local run flow, and API usage.

## Overview

The backend serves per-equity data to the frontend from a Supabase (Postgres) database.

- Framework: FastAPI + Uvicorn
- API base URL: http://localhost:8000/api
- Data source: Supabase database (`/api/equity/{symbol}`, `/api/equities`)
- CORS enabled for local frontend origins:
  - http://localhost:5173
  - http://localhost:3000

## Installation

### 1. Prerequisites

- Python 3.9+ (the `supabase` 2.x SDK drops 3.8; 3.11 recommended)
- pip
- Node.js (for full app workflow, not required to run backend alone)

### 2. Create and activate virtual environment (recommended)

```bash
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# Windows (cmd)
.venv\Scripts\activate.bat

# macOS/Linux
source .venv/bin/activate
```

### 3. Install backend dependencies

```bash
pip install -r backend/requirements.txt
```

Current required packages (see backend/requirements.txt):
- fastapi
- uvicorn
- python-multipart
- python-dotenv
- supabase  (the official SDK — install `supabase`, NOT `supabase-py`)

### 4. Supabase necessities

Supabase is now **required to run the backend at all**: the app's startup (lifespan) reads a
`.env` and creates a Supabase client, and raises immediately if it can't.

Create a `.env` at the **repo root** (the parent of `backend/`) with:

```
VITE_SUPABASE_URL=<your-supabase-url>
VITE_SUPABASE_PUBLISHABLE_KEY=<your-anon/publishable-key>
```

These can point at a hosted Supabase project or a local instance. For local DB work
(migrations, seed data) you also need:
- Docker Desktop (must be running)
- Supabase CLI

Common Supabase commands (from repo root):

```bash
supabase start
supabase db reset
```

If CLI is not globally installed:

```bash
npx supabase start
npx supabase db reset
```

## Setup Instructions

### 1. Verify Supabase connection

The backend reads all data from Supabase (Postgres), not local files. Ensure the repo-root `.env`
has `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` (see step 4 above) — the backend raises
at startup if they're missing.

### 2. Optional health verification before frontend run

After starting backend, verify:

- http://localhost:8000/api/health

## Running Instructions

### Run backend only

Run as a module **from the repo root** (not `python backend/main.py` — the absolute
`from backend import ...` imports require the repo root on `sys.path`):

```bash
python -m backend.main
# or:
uvicorn backend.main:app --port 8000
```

Backend listens on:
- http://127.0.0.1:8000

Interactive docs:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Run full app locally (backend + frontend)

Use two terminals from repository root.

Terminal A:

```bash
python -m backend.main
```

Terminal B:

```bash
npm run dev
```

## API Endpoints

### GET /api/health

Returns service health.

### GET /api/equities

Returns the list of active ticker symbols (from the `securities` table) for the ticker search.

### GET /api/equity/{symbol}

The main **Supabase-backed** endpoint. Resolves the ticker to a `security_id`, then aggregates
several DB queries in parallel into one payload. Current keys: `symbol, security, volatility_history,
price_history, options_chain, ai_overview, latest_shap_snapshot, distribution_data, events`.

Note: `distribution_data` is **live (stock scope)** — RV/IV/VRP histograms computed in plain
Python (`backend/distributions.py`) from the already-fetched `volatility_history`, not via an RPC
(the old `get_distribution` RPC timed out and was removed). It's derived after the gather and
never raises (returns `[]` on no data), so it can't fail the payload. Because all the DB queries
share one `asyncio.gather`, any single failing query still returns an error for the whole payload.

### GET /api/dashboard, /api/sector/{sector}, /api/macro

Unimplemented stubs — currently return `{}`.

## Example Usage

### cURL examples

```bash
# Health check
curl http://localhost:8000/api/health

# List active tickers
curl http://localhost:8000/api/equities

# Fetch one equity payload
curl http://localhost:8000/api/equity/AAPL
```

### Browser examples

- http://localhost:8000/api/health
- http://localhost:8000/api/equities
- http://localhost:8000/api/equity/AAPL

## Example Responses

### GET /api/health

```json
{
  "status": "ok"
}
```

### GET /api/equities

```json
{
  "equities": ["AAPL", "ADBE", "AMD", "AMZN"],
  "count": 16
}
```

### GET /api/equity/AAPL (shape excerpt)

```json
{
  "symbol": "AAPL",
  "security": { "company_name": "Apple Inc.", "gics_sector": "Information Technology" },
  "volatility_history": [],
  "price_history": [],
  "options_chain": [],
  "ai_overview": null,
  "latest_shap_snapshot": [],
  "events": []
}
```

## Troubleshooting

- 404 from `/api/equity/{symbol}`:
  - Confirm the ticker exists in the `securities` table (symbols are case-insensitive in the API)
- Empty ticker list from `/api/equities`:
  - Confirm the `securities` table has rows with `active = true` and Supabase creds are valid
- Frontend cannot load data:
  - Confirm backend is running on port 8000
  - Confirm frontend API base URL is set to http://localhost:8000/api
- Backend won't start / `.env file not found` at startup:
  - Create `.env` at the repo root with `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`
- `ModuleNotFoundError: No module named 'backend'`:
  - Launch from the repo root as `python -m backend.main` (not `python backend/main.py`)
- `ImportError: cannot import name 'acreate_client'` or `No module named 'supabase'`:
  - Install the official SDK: `pip install supabase` (the requirements name is `supabase`, not `supabase-py`)
- 500 from `/api/equity/{symbol}`:
  - Confirm the ticker exists in the `securities` table and Supabase creds are valid

## Current vs Planned Data Backend

Current:
- Supabase-backed query layer for `/api/equity/{symbol}` and `/api/equities` (see backend/database.py)

Planned:
- Migrate the remaining endpoints (dashboard/sector/macro stubs) to Supabase
- Extend `distribution_data` beyond stock scope (sector/market) — deferred; would need a
  cross-sectional query that avoids the 57014 timeout the original `get_distribution` RPC hit
- Optional caching layer for frequently accessed tickers

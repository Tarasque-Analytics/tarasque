# Backend Guide

This guide covers the current FastAPI backend used by the app team, including setup, local run flow, and API usage.

## Overview

The backend serves equity data to the frontend from two sources (mid-migration):
file-backed ticker payloads and a Supabase (Postgres) database.

- Framework: FastAPI + Uvicorn
- API base URL: http://localhost:8000/api
- Data sources:
  - Legacy file payloads: app/assets/data/*_Payload.json (`/api/tickers*`)
  - Supabase database: `/api/equity/{symbol}`
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

### 1. Verify expected data location

The backend reads payloads from:

- app/assets/data

Expected naming format:

- {SYMBOL}_Payload.json

Examples:
- AAPL_Payload.json
- MSFT_Payload.json

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

### GET /api/tickers

Returns all available tickers derived from payload filenames.

### GET /api/tickers/{symbol}

Returns full payload JSON for a ticker symbol (case-insensitive). (File-backed.)

### GET /api/equity/{symbol}

The main **Supabase-backed** endpoint. Resolves the ticker to a `security_id`, then aggregates
several DB queries in parallel into one payload. Current keys: `symbol, volatility_history,
price_history, options_chain, ai_overview, latest_shap_snapshot, events`.

Note: `distribution_data` is temporarily disabled (the `get_distribution` RPC times out —
tracked in a separate issue/PR). Because all queries share one `asyncio.gather`, any single
failing query returns an error for the whole payload.

### GET /api/dashboard, /api/sector/{sector}, /api/macro

Unimplemented stubs — currently return `{}`.

## Example Usage

### cURL examples

```bash
# Health check
curl http://localhost:8000/api/health

# List tickers
curl http://localhost:8000/api/tickers

# Fetch one ticker payload
curl http://localhost:8000/api/tickers/AAPL
```

### Browser examples

- http://localhost:8000/api/health
- http://localhost:8000/api/tickers
- http://localhost:8000/api/tickers/AAPL

## Example Responses

### GET /api/health

```json
{
  "status": "ok"
}
```

### GET /api/tickers

```json
{
  "tickers": ["AAPL", "ADBE", "AMD", "AMZN"],
  "count": 16
}
```

### GET /api/tickers/AAPL (shape excerpt)

```json
{
  "meta": {
    "ticker": "AAPL",
    "timestamp": "2026-02-24 17:03",
    "spot_price": 272.14,
    "forecast_rv": {
      "21": 0.2161,
      "63": 0.2025,
      "126": 0.1975
    },
    "garch_21d": 0.2747,
    "market_iv_atm": 0.2672,
    "vrp_wedge": 0.0364
  },
  "hedging": {
    "recipe": {},
    "interpretation": "Factor Hedge Positions"
  },
  "explainability": {
    "drivers": {}
  },
  "charts": {
    "monte_carlo": {}
  }
}
```

## Troubleshooting

- 404 for ticker endpoint:
  - Confirm file exists in app/assets/data
  - Confirm symbol matches file prefix (case-insensitive in API)
- Empty ticker list:
  - Confirm app/assets/data exists and contains *_Payload.json files
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

Current (mid-migration):
- File-backed payload API from app/assets/data (`/api/tickers*`)
- Supabase-backed query layer for `/api/equity/{symbol}` (see backend/database.py)

Planned:
- Migrate the remaining endpoints (dashboard/sector/macro stubs) to Supabase
- Re-enable `distribution_data` once the `get_distribution` RPC is fixed (separate PR)
- Optional caching layer for frequently accessed tickers

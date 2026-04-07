# Backend Guide

This guide covers the current FastAPI backend used by the app team, including setup, local run flow, and API usage.

## Overview

The backend currently serves ticker payload JSON files to the frontend.

- Framework: FastAPI + Uvicorn
- API base URL: http://localhost:8000/api
- Data source: app/assets/data/*_Payload.json
- CORS enabled for local frontend origins:
  - http://localhost:5173
  - http://localhost:3000

## Installation

### 1. Prerequisites

- Python 3.8+
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

Current required packages:
- fastapi
- uvicorn
- python-multipart

### 4. Supabase necessities

Supabase is not required for the current file-backed backend API.

Supabase is needed only when you are working on database/migration tasks.

If you are doing DB work, install and run:
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

```bash
python backend/main.py
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
python backend/main.py
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

Returns full payload JSON for a ticker symbol (case-insensitive).

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

## Current vs Planned Data Backend

Current:
- File-backed payload API from app/assets/data

Planned:
- PostgreSQL/Supabase-backed API with migrations, query layer, and optional caching
- When that work begins, update this guide with connection config and DB-first run flow

# Contributing (App Developers)

This document is for application developers working on the frontend, backend API, and app delivery workflows.

Model-development contribution practices are intentionally out of scope here.

## 1. App Framework Overview

Current app stack:
- Frontend: React 19, React Router 7 (SSR enabled), TypeScript, Vite 7, Tailwind CSS 4, Chart.js.
- Backend: FastAPI (Python), serving per-equity data over REST endpoints.
- Data source for app: Supabase (Postgres) database, queried by the backend (`backend/database.py`).

Infrastructure track:
- CI/CD: GitHub Actions (`.github/workflows/ci.yml`) runs lint/format, typecheck, the frontend/
  backend/automation tests, and build on every PR to `main` (see §7). CI-driven *deployment* is
  still planned (see §5.4).
- Testing: Vitest for frontend unit tests (Playwright end-to-end still planned).
- Deployment: Containerized frontend path exists today (Dockerfile). CI-driven deployment target is planned after test gates are in place.

## 2. Quickstart Commands for Local Development

What must be running:
- Backend API (port 8000)
- Frontend dev server (port 5173)

Install once:

```bash
npm install
pip install -r backend/requirements.txt
```

Run day-to-day (two terminals):

```bash
# Terminal A: backend
python backend/main.py

# Terminal B: frontend
npm run dev
```

Useful local URLs:
- Frontend: `http://localhost:5173`
- Backend health: `http://localhost:8000/api/health`
- API docs: `http://localhost:8000/docs`

## 3. Frontend Development

### 3.1 Start frontend

```bash
npm install
npm run dev
```

This starts React Router dev mode with HMR.

### 3.2 Type checking

```bash
npm run typecheck
```

Run this before opening a PR.

### 3.3 Build and local production run

```bash
npm run build
npm run start
```

This validates the SSR production bundle and app server path.

### 3.4 Frontend-backend API contract note

Frontend API calls currently target:
- `http://localhost:8000/api`

If backend host/port changes, update the API base URL in `app/utils/database.ts`.

## 4. Backend Development

### 4.1 Environment setup

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r backend/requirements.txt
```

### 4.2 Start backend

```bash
python backend/main.py
```

The FastAPI service runs at `http://localhost:8000`.

### 4.3 API endpoints used by the app

- `GET /api/health`
- `GET /api/equities` (active ticker list for search)
- `GET /api/equity/{symbol}` (composite per-equity payload)

### 4.4 Data expectations

The backend reads per-equity data from Supabase (Postgres), not local files. It requires a `.env`
at the repo root with `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` and raises at startup
if they're missing (see `backend/CLAUDE.md` / `backend/BACKEND_GUIDE.md`).

If equity pages fail to load, verify the backend is running and Supabase creds/connection are valid.

## 5. Build and Deploy

### 5.1 Build app artifacts

```bash
npm run build
```

Output:
- `build/client`
- `build/server`

### 5.2 Run built app

```bash
npm run start
```

### 5.3 Container build/run (frontend)

```bash
docker build -t tarasque-app .
docker run -p 3000:3000 tarasque-app
```

### 5.4 Planned deployment path

Near-term recommended path:
1. CI job runs install + typecheck + build.
2. Optional test stage (Vitest/Playwright) gates merge and deploy.
3. Deploy built container/image to target environment.

## 6. Collaboration Workflow

Before you start work:

```bash
git pull
```

Submit work:

```bash
git add .
git commit -m "Describe your change"
git push
```

Recommended PR checklist:
- Frontend starts and loads at `http://localhost:5173`
- Backend starts and responds at `/api/health`
- `npm run lint:check` and `npm run format:check` pass (run `npm run lint && npm run format` to auto-fix)
- `npm run typecheck` passes
- `npm run test` passes (frontend + backend + automation)
- `npm run build` passes

CI runs all of these on every PR to `main` (see §7) — failures block merge once branch protection
requires the checks.

## 7. Code Quality & CI

### 7.1 Linting & formatting

Two stacks, two tools: **ESLint + Prettier** for the frontend (`app/`) and **Ruff** (lint + format)
for the Python (`backend/`, `automation/`). The `model/` directory is owned by a separate team and
is **never** linted or formatted.

Run from the repo root:

```bash
npm run lint            # auto-fix: ESLint --fix (app) + Ruff check --fix (backend, automation)
npm run format          # auto-format: Prettier (app) + Ruff format (backend, automation)
npm run lint:check      # report only, no changes (what CI runs)
npm run format:check    # report only, no changes (what CI runs)
```

Touched only one stack? Use the per-stack variants: `lint:app` / `lint:py` and `format:app` /
`format:py` (each with a `:check` suffix). Tooling installs via `npm install` (JS) and
`pip install -r backend/requirements-dev.txt` (Ruff, pinned). Tip: `npm run lint && npm run format`
fixes your whole branch in one pass — then `git diff` to review.

### 7.2 Tests

```bash
npm run test            # all three suites
npm run test:frontend   # Vitest (app/)
npm run test:backend    # pytest (backend/tests) — live DB tests skip without Supabase creds
npm run test:automation # pytest (automation/tests)
```

### 7.3 Continuous integration

Every pull request to `main` runs [`.github/workflows/ci.yml`](.github/workflows/ci.yml) — six
independent checks, each of which must pass to merge (once branch protection requires them):
**lint/format**, **typecheck**, **frontend tests**, **backend tests**, **automation tests**, and
**build**. The jobs run the same commands you run locally; none need secrets (the live DB tests
skip without creds). Node 20, Python 3.11, with npm + pip caching.
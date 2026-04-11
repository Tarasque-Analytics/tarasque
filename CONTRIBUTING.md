# Contributing (App Developers)

This document is for application developers working on the frontend, backend API, and app delivery workflows.

Model-development contribution practices are intentionally out of scope here.

## 1. App Framework Overview

Current app stack:
- Frontend: React 19, React Router 7 (SSR enabled), TypeScript, Vite 7, Tailwind CSS 4, Chart.js.
- Backend: FastAPI (Python), serving ticker payload JSON data over REST endpoints.
- Data source for app: `app/assets/data/*_Payload.json` via backend API. (Migrate to database)

Planned infrastructure track:
- CI/CD: GitHub Actions workflow for install, typecheck, lint/test (when present), and build.
- Testing: Vitest for frontend unit tests and Playwright for end-to-end tests.
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

If backend host/port changes, update the API base URL in `app/utils/tickers.ts`.

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
- `GET /api/tickers`
- `GET /api/tickers/{symbol}`

### 4.4 Data expectations

The backend reads ticker payload files from:
- `app/assets/data`

Naming convention:
- `{SYMBOL}_Payload.json` (example: `AAPL_Payload.json`)

If ticker pages fail to load, verify files exist and backend is running.

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
docker build -t volarbmodel-app .
docker run -p 3000:3000 volarbmodel-app
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
- `npm run typecheck` passes
- `npm run build` passes
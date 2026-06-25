# Docker Deployment Guide

This guide explains how to build and deploy the Volarbmodel application using Docker and Docker Compose.

## Overview

The deployment includes two Docker containers orchestrated by Docker Compose:
- **Frontend**: React Router application with Vite (Node.js 20-alpine)
- **Backend**: FastAPI application (Python 3.11-slim)

Both containers communicate over a dedicated Docker network (`volarbmodel-network`).

## Quick Start

### Prerequisites
- Docker and Docker Compose installed
- Ports 5173 and 8000 available
- `.env` file with Supabase credentials (see Environment Variables section)

### Deploy Full Stack

**On Windows (PowerShell):**
```powershell
.\docker-run.ps1
```

**On macOS/Linux (or Windows with WSL):**
```bash
docker-compose down --remove-orphans
docker-compose up --build
```

Access the application:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Documentation: http://localhost:8000/docs

### Stop Containers

```bash
docker-compose down
```

## Environment Configuration

### Required .env File

Create a `.env` file in the project root with your Supabase credentials:

```env
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=your-publishable-key
VITE_API_URL=http://backend:8000/api
```

**Important Notes:**
- `VITE_API_URL` should use `http://backend:8000/api` when running in Docker (service-to-service communication)
- In local development, use `http://localhost:8000/api` (or omit it — `app/utils/database.ts` falls back to that value when `VITE_API_URL` is unset)
- The `VITE_*` prefix is required for Vite to expose variables to the frontend at build time
- The `.env` file is excluded from Docker builds for security (see `.dockerignore`)

### Build-Time Environment Variables

The frontend requires Vite environment variables at **build time**, not runtime. The Dockerfile achieves this by:

1. Accepting `ARG` parameters for Supabase credentials and API URL
2. Converting `ARG` to `ENV` *by reference* (`ENV VITE_API_URL=$VITE_API_URL`) before running `npm run build`
3. Vite statically replaces `import.meta.env.VITE_*` references with actual values during compilation

This ensures the credentials are baked into the JavaScript bundle. Because the values are inlined at build time, **rebuild the frontend image whenever any `VITE_*` value changes** — passing them only at runtime has no effect on an already-built bundle.

**Canonical build path — don't pass `--build-arg` by hand.** Always build through `docker-compose build` (or `./docker-run.ps1` on Windows). Both read the three `VITE_*` values from your `.env` and pass them as build args automatically, so the correct per-environment values are encoded in `.env`, not in anyone's memory. A guard in the `Dockerfile` fails the build immediately if `VITE_SUPABASE_URL` / `VITE_SUPABASE_PUBLISHABLE_KEY` are missing, so a misconfigured build can't silently produce a broken image. For a prod/ECS image, supply those three values to the build from the CI environment (or `--env-file`) — never hardcode them in the Dockerfile.

## Windows PowerShell Deployment (docker-run.ps1)

The `docker-run.ps1` script automates the deployment process on Windows:

```powershell
# Reads .env file line-by-line
# Parses KEY=VALUE pairs, removing quotes
# Passes values explicitly to docker build as --build-arg
# Runs docker-compose down and docker-compose up
.\docker-run.ps1
```

This script handles Windows PowerShell's environment variable substitution quirks and ensures Supabase credentials are correctly passed to the Docker build process.

## Docker Architecture

### Multi-Stage Frontend Build

The Dockerfile uses 4 stages for optimal image size and caching:

1. **development-dependencies-env**: Installs all dependencies (dev + prod)
2. **production-dependencies-env**: Installs only production dependencies
3. **build-env**: Builds the Vite application with environment variables
4. **final**: Minimal runtime image with only necessary files

### Frontend Service Details

- **Base Image**: `node:20-alpine` (~173 MB)
- **Build Args**: `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, `VITE_API_URL`
- **Port**: 5173
- **Health Check**: `GET /` every 30 seconds
- **Restart Policy**: unless-stopped

### Backend Service Details

- **Base Image**: `python:3.11-slim` (~125 MB)
- **Port**: 8000
- **Health Check**: Curl request to `/api/health` every 30 seconds
- **Restart Policy**: unless-stopped
- **Environment**: Supabase async client, PostgreSQL connection

## Building Individually

### Build Frontend Only

```bash
# NOTE: this bare build FAILS — a Dockerfile guard rejects it because
# VITE_SUPABASE_URL / VITE_SUPABASE_PUBLISHABLE_KEY have no defaults. Pass them
# (see below), or just build via docker-compose / docker-run.ps1 (they read .env).
docker build -t volarbmodel-frontend .

# With environment variables
docker build \
  --build-arg VITE_SUPABASE_URL="https://your-project.supabase.co" \
  --build-arg VITE_SUPABASE_PUBLISHABLE_KEY="your-publishable-key" \
  --build-arg VITE_API_URL="http://backend:8000/api" \
  -t volarbmodel-frontend .
```

### Build Backend Only

```bash
docker build -t volarbmodel-backend ./backend
```

### Run Containers Individually

```bash
# Frontend (port 5173)
docker run -p 5173:5173 volarbmodel-frontend

# Backend (port 8000)
docker run -p 8000:8000 volarbmodel-backend
```

## Networking

Containers communicate via a custom Docker bridge network:

```yaml
networks:
  volarbmodel-network:
    driver: bridge
```

**Internal Service Names:**
- Frontend can reach backend at: `http://backend:8000`
- Backend does not need to reach frontend

## Docker Best Practices Implemented

✅ **Multi-stage builds** — Reduces final image size by excluding build dependencies
✅ **Alpine base images** — Minimal base images (~173 MB for Node, ~125 MB for Python)
✅ **Build cache optimization** — Dependencies cached separately from application code
✅ **Health checks** — Container orchestration can monitor app health
✅ **.dockerignore** — Optimized build context (excludes node_modules, dist, .git, etc.)
✅ **Non-root user** — Improves security posture
✅ **Proper signal handling** — Graceful shutdowns
✅ **Environment variable separation** — Build-time vs. runtime configuration

## Production Deployment

### Docker Registry Deployment

1. **Build and tag images for registry:**
   ```bash
   docker build \
     --build-arg VITE_SUPABASE_URL="your-production-url" \
     --build-arg VITE_SUPABASE_PUBLISHABLE_KEY="your-key" \
     --build-arg VITE_API_URL="https://api.yourdomain.com" \
     -t yourregistry/volarbmodel-frontend:latest .
   
   docker build -t yourregistry/volarbmodel-backend:latest ./backend
   ```

2. **Push to registry:**
   ```bash
   docker push yourregistry/volarbmodel-frontend:latest
   docker push yourregistry/volarbmodel-backend:latest
   ```

3. **Deploy to hosting platform** (AWS ECS, Azure Container Instances, DigitalOcean App Platform, etc.)

### Environment Variables in Production

Update your deployment platform's environment configuration with:
- `VITE_SUPABASE_URL`: Your production Supabase project URL
- `VITE_SUPABASE_PUBLISHABLE_KEY`: Your production Supabase key
- `VITE_API_URL`: Your production backend API URL (e.g., `https://api.yourdomain.com`)
- `NODE_ENV`: Set to `production`

## Troubleshooting

### Frontend shows "API unavailable" or "Supabase credentials missing"

**Problem**: Environment variables are undefined in the browser.

**Solution**: 
1. Verify `.env` file exists in project root
2. Check that `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` are set
3. Rebuild with `docker-compose up --build` to embed variables
4. Check browser console (DevTools) for actual values being loaded

### Backend cannot connect to Supabase

**Problem**: Backend errors about Supabase connection.

**Solution**:
1. Verify `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` in `.env`
2. Check that Supabase project is accessible from your network
3. Review backend logs: `docker-compose logs backend`

### Container exits immediately

**Problem**: `docker-compose up` shows container exiting after a few seconds.

**Solution**:
1. Check logs: `docker-compose logs frontend` or `docker-compose logs backend`
2. Verify all required environment variables are in `.env`
3. Ensure ports 5173 and 8000 are not in use by other services

### Port already in use

**Problem**: Error "Port 5173 is already allocated"

**Solution**:
```bash
# Stop all containers
docker-compose down

# Or use different ports
docker run -p 5174:5173 volarbmodel-frontend
```

### Build fails
- Clear Docker cache: `docker system prune -a`
- Rebuild: `docker-compose up --build`

## Performance Tips

- **Layer caching**: Dockerfile stages cache dependencies separately; only rebuild when package.json changes
- **Health checks**: Allow orchestrators to detect and restart unhealthy containers
- **Resource limits**: Consider adding memory/CPU limits in production docker-compose
- **Image size**: Alpine base images keep total image size under 400 MB combined

## Security Considerations

⚠️ **Never commit `.env` file to git** — add to `.gitignore`
⚠️ **Supabase keys in .env** — treated as build secrets; consider using Docker secrets in production
⚠️ **API URL in bundle** — `VITE_API_URL` is visible in the browser; use CORS policies for security
⚠️ **Health check endpoints** — The backend health-checks `GET /api/health` and the frontend `GET /`; keep those reachable or adjust the checks in `docker-compose.yml` / the Dockerfiles.

## Environment-Specific Deployment

The Dockerfile uses multi-stage builds which are optimized for production. For development, you may want to:

1. Skip the build optimization
2. Enable hot-reload with volume mounts
3. Use different environment variables

Consider creating a `docker-compose.dev.yml` for local development with:
- Volume mounts for code directories
- Development environment variables
- Exposed ports for debugging

> Note: the base `docker-compose.yml` currently bind-mounts `./backend:/app/backend`,
> which overrides the code baked into the backend image with the host tree. That
> belongs in a dev override; remove it from the base file before treating the
> compose stack as production.

## Notes on build-time environment variables (resolved)

Earlier iterations of this branch hit a problem where the Vite env vars
(`VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, `VITE_API_URL`) were not
embedded into the frontend bundle, so the app fell back to
`http://localhost:8000/api` and the Supabase client could not initialize.

This is now resolved:

- **`Dockerfile`** declares the three `ARG`s and converts them to `ENV` *by
  reference* (`ENV VITE_API_URL=$VITE_API_URL`, etc.) before `npm run build`, so
  the build args passed by `docker-compose.yml` / `docker-run.ps1` actually reach
  Vite and are statically baked into the bundle.
- **`app/utils/database.ts`** reads `import.meta.env.VITE_API_URL` and falls back
  to `http://localhost:8000/api` only when it is unset, so local `npm run dev`
  still targets the local backend.
- **`app/supabaseClient.ts`** fails fast with a clear error if no Supabase
  credentials are present, instead of silently constructing an empty client.

Because Vite inlines these values at **build time**, rebuild the frontend image
whenever any `VITE_*` value changes — passing them only at runtime has no effect
on an already-built bundle.

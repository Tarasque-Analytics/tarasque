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
- In local development, use `http://localhost:8000/api`
- The `VITE_*` prefix is required for Vite to expose variables to the frontend at build time
- The `.env` file is excluded from Docker builds for security (see `.dockerignore`)

### Build-Time Environment Variables

The frontend requires Vite environment variables at **build time**, not runtime. The Dockerfile achieves this by:

1. Accepting `ARG` parameters for Supabase credentials and API URL
2. Converting `ARG` to `ENV` before running `npm run build`
3. Vite statically replaces `import.meta.env.VITE_*` references with actual values during compilation

This ensures the credentials are baked into the JavaScript bundle.

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
- **Health Check**: HTTP endpoint check every 30 seconds
- **Restart Policy**: unless-stopped

### Backend Service Details

- **Base Image**: `python:3.11-slim` (~125 MB)
- **Port**: 8000
- **Health Check**: Curl request to `/docs` every 30 seconds
- **Restart Policy**: unless-stopped
- **Environment**: Supabase async client, PostgreSQL connection

## Building Individually

### Build Frontend Only

```bash
# Without environment variables (uses defaults)
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
1. Verify `SUPABASE_URL` and `SUPABASE_ANON_KEY` in `.env`
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

## Performance Tips

- **Layer caching**: Dockerfile stages cache dependencies separately; only rebuild when package.json changes
- **Health checks**: Allow orchestrators to detect and restart unhealthy containers
- **Resource limits**: Consider adding memory/CPU limits in production docker-compose
- **Image size**: Alpine base images keep total image size under 400 MB combined

## Security Considerations

⚠️ **Never commit `.env` file to git** — add to `.gitignore`
⚠️ **Supabase keys in .env** — treated as build secrets; consider using Docker secrets in production
⚠️ **API URL in bundle** — `VITE_API_URL` is visible in the browser; use CORS policies for security
⚠️ **Health check endpoints** — Ensure `/docs` endpoint is accessible or adjust health check accordingly

### Container exits immediately
```bash
docker-compose logs frontend
docker-compose logs backend
```

### Port already in use
Change ports in docker-compose.yml:
```yaml
ports:
  - "8000:3000"  # Host:Container
  - "9000:8000"
```

### Build fails
- Clear Docker cache: `docker system prune -a`
- Rebuild: `docker-compose up --build`

## Environment-Specific Deployment

The Dockerfile uses multi-stage builds which are optimized for production. For development, you may want to:

1. Skip the build optimization
2. Enable hot-reload with volume mounts
3. Use different environment variables

Consider creating a `docker-compose.dev.yml` for local development with:
- Volume mounts for code directories
- Development environment variables
- Exposed ports for debugging

## Current Issues

### Frontend-Backend Communication: Environment Variables Not Embedding in Vite Bundle

**Problem:**
The frontend container is unable to query the backend API because Vite environment variables (`VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, `VITE_API_URL`) are not being embedded into the JavaScript bundle during the Docker build process. As a result:
- The frontend falls back to `http://localhost:8000/api` instead of `http://backend:8000/api`(hardcoded default, handled in database.ts)
- API requests fail when the frontend container tries to reach `localhost` (which doesn't exist in the container context)
- The Supabase client cannot initialize due to missing credentials
- Console errors: "supabaseUrl is required."

**Root Cause:**
Vite requires environment variables to be available at **build time** (when `npm run build` runs), not at runtime. Variables must be replaced in the source code during compilation to be available via `import.meta.env.VITE_*`. Simply passing them as runtime environment variables does not work.

**Attempts Made to Fix:**

1. **Attempt 1: ENV statements in Dockerfile**
   - Used `ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL` after ARG declaration
   - Result: Variables did not reach npm run build; vite.config.ts debug logs never appeared
   - Issue: ENV after ARG only applies to subsequent layers, not the RUN command in the same layer

2. **Attempt 2: Inline RUN command with variable export**
   - Changed to: `RUN VITE_API_URL=$VITE_API_URL npm run build`
   - Result: Still undefined; variables not visible to Vite
   - Issue: Shell variable syntax did not properly export to child process

3. **Attempt 3: .env.production with .env file creation**
   - Created `.env.production` with placeholder values
   - Modified Dockerfile RUN to create `.env` file before build: `echo "VITE_API_URL=..." >> .env`
   - Result: Vite still read placeholders, not actual values
   - Issue: .env file was created but values not substituted from ARG before file write

4. **Attempt 4: Medium article "build once, inject later" approach**
   - Created `.env.production` with placeholders: `VITE_API_URL=PREFIX_API_URL`
   - Implemented `env.sh` script to run at container startup using sed replacement
   - Modified Dockerfile with entrypoint to run injection before `npm start`
   - Result: sed replacement did not find or modify placeholders in built JavaScript
   - Issue: Likely because sed pattern matching or file paths were incorrect; reverted

5. **Current Approach: ARG → ENV with docker-compose build args**
   - Using Dockerfile: `ARG VITE_API_URL` then `ENV VITE_API_URL=$VITE_API_URL` before RUN
   - Using docker-compose: `args:` section to pass `${VITE_API_URL}` from .env
   - Using docker-run.ps1: Explicitly parsing .env and passing `--build-arg` to docker build
   - Status: Build args are confirmed to be passed (visible in docker output), but still not reaching npm
   - Issue: Unknown; variables reach docker build command but not npm run build subprocess

**Evidence:**
- Debug logging added to database.ts shows `import.meta.env.VITE_API_URL` is `undefined` in the browser
- Console logs in vite.config.ts do not appear in build output, indicating Vite is not receiving the variables
- Frontend falls back to hardcoded `http://localhost:8000/api`
- Backend is working correctly and responds to requests (verified with wget tests)
- Network communication between containers is working — verified with:
  ```bash
  docker-compose exec frontend wget -O- http://backend:8000/api/equity/AAPL
  ```
  This command successfully retrieved the full equity data JSON payload from the backend, proving that:
  - The frontend container can resolve the `backend` service name via Docker's internal DNS
  - The backend is running and accessible on port 8000
  - The API endpoint `/api/equity/AAPL` is functional

**Next Steps to Investigate:**
1. Verify the exact syntax for passing ARG values to npm/Vite during RUN
2. Check if npm scripts have special environment variable handling that requires different syntax
3. Consider alternative: using a build script wrapper that logs environment variables before calling npm
4. Explore whether Vite config needs explicit handling of undefined variables
5. Review Vite build process documentation for how it discovers and uses environment variables

**Workaround (Not Recommended for Production):**
The frontend can be built locally with the correct .env file, then the built `/build` directory committed and deployed without rebuilding in Docker. This defeats the purpose of containerization but would allow the app to function. 

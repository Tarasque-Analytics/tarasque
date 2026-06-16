# Docker Deployment Guide

This guide explains how to build and deploy the Volarbmodel application using Docker.

## Overview

The deployment includes two Docker containers:
- **Frontend**: React Router application (Node.js)
- **Backend**: FastAPI application (Python)

## Quick Start

### Prerequisites
- Docker and Docker Compose installed
- Port 3000 and 8000 available

### Deploy Full Stack

```bash
docker-compose up --build
```

Access the application:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

### Stop Containers

```bash
docker-compose down
```

## Building Individually

### Build Frontend Only

```bash
docker build -t volarbmodel-frontend .
docker run -p 3000:3000 volarbmodel-frontend
```

### Build Backend Only

```bash
docker build -t volarbmodel-backend ./backend
docker run -p 8000:8000 volarbmodel-backend
```

## Development Mode

To run with hot-reload for development, use docker-compose with volume mounts:

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

## Production Deployment

### Using Docker Only

1. Build and push images to Docker registry:
```bash
docker build -t yourregistry/volarbmodel-frontend:latest .
docker build -t yourregistry/volarbmodel-backend:latest ./backend
docker push yourregistry/volarbmodel-frontend:latest
docker push yourregistry/volarbmodel-backend:latest
```

2. Deploy to your hosting platform (AWS ECS, Azure ACI, DigitalOcean App Platform, etc.)

### Environment Variables

Create a `.env` file for production (exclude from git):

```env
NODE_ENV=production
VITE_API_URL=https://api.yourdomain.com
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_supabase_key
```

Mount this in docker-compose:
```yaml
env_file:
  - .env
```

## Docker Best Practices Implemented

✅ **Multi-stage builds** - Reduces final image size
✅ **Non-root user** - Improves security
✅ **Health checks** - Enables container orchestration to monitor app health
✅ **dumb-init** - Proper signal handling for graceful shutdowns
✅ **.dockerignore** - Optimized build context
✅ **Alpine images** - Minimal base images for smaller footprint
✅ **Cache optimization** - Dependencies cached separately from code

## Troubleshooting

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

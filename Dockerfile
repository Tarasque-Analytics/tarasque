FROM node:20-alpine AS development-dependencies-env
COPY . /app
WORKDIR /app
RUN npm ci

FROM node:20-alpine AS production-dependencies-env
COPY ./package.json package-lock.json /app/
WORKDIR /app
RUN npm ci --omit=dev

FROM node:20-alpine AS build-env
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_PUBLISHABLE_KEY
ARG VITE_API_URL=http://backend:8000/api

# Set environment variables during build (convert ARG to ENV)
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL
ENV VITE_SUPABASE_PUBLISHABLE_KEY=$VITE_SUPABASE_PUBLISHABLE_KEY
ENV VITE_API_URL=$VITE_API_URL

# Fail the build early if the Supabase creds weren't supplied as build args. VITE_API_URL
# has a default; the Supabase vars do not, so a missing one would otherwise bake an empty
# value into the bundle (and the app would fail fast at runtime). Build via
# `docker-compose build` or `./docker-run.ps1` — they inject these from .env, so you never
# pass --build-arg by hand.
RUN test -n "$VITE_SUPABASE_URL" && test -n "$VITE_SUPABASE_PUBLISHABLE_KEY" || \
    (echo "ERROR: VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY build args are required. Build via 'docker-compose build' or './docker-run.ps1' (they read .env)." >&2 && exit 1)

COPY . /app/
COPY --from=development-dependencies-env /app/node_modules /app/node_modules
WORKDIR /app
RUN npm run build

FROM node:20-alpine
COPY ./package.json package-lock.json /app/
COPY --from=production-dependencies-env /app/node_modules /app/node_modules
COPY --from=build-env /app/build /app/build
WORKDIR /app
ENV PORT=5173
ENV HOST=0.0.0.0
CMD ["npm", "run", "start"]

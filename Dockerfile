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
ENV VITE_SUPABASE_URL="https://kynrztmoshssqduxhdsb.supabase.co"
ENV VITE_SUPABASE_PUBLISHABLE_KEY="sb_publishable_B2lyrSVn1xHnIcI8pH7T-Q_57o27mra"
ENV VITE_API_URL="https://api.tarasqueanalytics.com/api"

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
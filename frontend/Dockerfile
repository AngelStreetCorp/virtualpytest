# Build stage — Vite bakes VITE_* values into the bundle, so they are build args.
# (setup/docker/docker-compose.yml passes them from setup/docker/.env)
FROM node:22-alpine AS builder

ARG VITE_SERVER_URL=http://localhost:5109
ARG VITE_GRAFANA_URL=http://localhost:3000
ARG VITE_CLOUDFLARE_R2_PUBLIC_URL=
ARG VITE_SUPABASE_URL=
ARG VITE_SUPABASE_ANON_KEY=
ARG VITE_SERVER_PUBLIC_KEY=
ARG VITE_PROJECT_NAME=VirtualPyTest
ENV VITE_SERVER_URL=$VITE_SERVER_URL \
    VITE_GRAFANA_URL=$VITE_GRAFANA_URL \
    VITE_CLOUDFLARE_R2_PUBLIC_URL=$VITE_CLOUDFLARE_R2_PUBLIC_URL \
    VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY \
    VITE_SERVER_PUBLIC_KEY=$VITE_SERVER_PUBLIC_KEY \
    VITE_PROJECT_NAME=$VITE_PROJECT_NAME

WORKDIR /app

# the npm prebuild hook (scripts/prebuild.sh) and copy-docs.sh are bash scripts
RUN apk add --no-cache bash git

COPY package*.json ./
RUN npm ci

# Source (frontend/.dockerignore keeps node_modules, dist and .env* out)
COPY . .
RUN chmod +x scripts/*.sh && mkdir -p public/docs

# prebuild.sh (npm hook) skips the docs copy when ../docs is absent — expected here
RUN npm run build

# Runtime stage — static files served by `serve` on 5073 (SPA fallback)
FROM node:22-alpine

# node:22-alpine already owns uid 1000 (user `node`); let adduser pick the uid
RUN adduser -D vpt_user && npm install -g serve@14

COPY --from=builder /app/dist /app/dist
RUN chown -R vpt_user:vpt_user /app

EXPOSE 5073
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:5073/ || exit 1

USER vpt_user
CMD ["serve", "-s", "/app/dist", "-l", "5073"]

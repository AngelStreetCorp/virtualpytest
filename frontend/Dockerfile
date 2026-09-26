# Build stage.
#
# The VITE_* build args below are now a FALLBACK, not the configuration: the runtime
# entrypoint writes /app/dist/config.js from the container's environment and getEnv()
# (src/config/constants.ts) prefers that. This is what makes the image publishable —
# one build serves any PUBLIC_HOST. Passing them at build time still works and is what
# the native (non-container) install does.
FROM node:22-alpine AS builder

ARG VITE_SERVER_URL=http://localhost:5109
ARG VITE_GRAFANA_URL=http://localhost:3000
ARG VITE_CLOUDFLARE_R2_PUBLIC_URL=
ARG VITE_SUPABASE_URL=
ARG VITE_SUPABASE_ANON_KEY=
ARG VITE_SERVER_PUBLIC_KEY=
ARG VITE_PROJECT_NAME=VirtualPyTest
# Release tag passed in by .github/workflows/release-images.yml as a build-arg.
# prebuild.sh reads this to synthesize a version.txt when the repo-root VERSION.txt
# isn't reachable from the frontend-only build context (it isn't, see BUG-0117
# follow-up). Including it as an ARG also adds the value to the cache key for
# the next RUN layer, which is what actually invalidates the stale-cache layer.
ARG VPT_IMAGE_TAG
ENV VITE_SERVER_URL=$VITE_SERVER_URL \
    VITE_GRAFANA_URL=$VITE_GRAFANA_URL \
    VITE_CLOUDFLARE_R2_PUBLIC_URL=$VITE_CLOUDFLARE_R2_PUBLIC_URL \
    VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY \
    VITE_SERVER_PUBLIC_KEY=$VITE_SERVER_PUBLIC_KEY \
    VITE_PROJECT_NAME=$VITE_PROJECT_NAME \
    VPT_IMAGE_TAG=$VPT_IMAGE_TAG

WORKDIR /app

# the npm prebuild hook (scripts/prebuild.sh) and copy-docs.sh are bash scripts
RUN apk add --no-cache bash git

COPY package*.json ./
RUN npm ci

# Source (frontend/.dockerignore keeps node_modules, dist and .env* out)
COPY . .
RUN chmod +x scripts/*.sh && mkdir -p public/docs

# prebuild.sh (npm hook) skips the docs copy when ../docs is absent — expected here
# VPT_IMAGE_TAG is read by prebuild.sh to synthesize frontend/public/version.txt
# when the repo root's VERSION.txt isn't in the build context.
RUN npm run build

# Runtime stage — static files served by `serve` on 5073 (SPA fallback)
FROM node:22-alpine

# node:22-alpine already owns uid 1000 (user `node`); let adduser pick the uid
RUN adduser -D vpt_user && npm install -g serve@14

COPY --from=builder /app/dist /app/dist
RUN chown -R vpt_user:vpt_user /app

COPY --from=builder /app/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5073
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:5073/ || exit 1

USER vpt_user
# Writes dist/config.js from the environment, then serves. See frontend/docker/entrypoint.sh
CMD ["/entrypoint.sh"]

# API Coverage

This project keeps API docs as a manually curated set of OpenAPI specs in `docs/api/specs/`.

## What Is The Source Of Truth

- Backend routes live in `backend_server/src/routes/`
- Public API specs live in `docs/api/specs/*.yaml`
- Rendered HTML docs are generated into `docs/api/docs/`
- Frontend API docs UI is the selector in `frontend/src/pages/ApiDocumentation.tsx`

## How The Docs Set Works

The docs UI does not discover endpoints dynamically.

Instead, we maintain a small number of grouped specs, each covering one public API family. This keeps the selector readable and avoids showing every internal callback or low-level route as a separate document.

Current grouped coverage includes:

- System
- Device
- Navigation
- User Interface
- Script
- Testcase
- Campaign
- Deployment & Scheduling
- Requirements
- AI Analysis
- Metrics & Analytics
- Access & Workspace
- Results & Reporting

## What We Intentionally Group Or Exclude

Some server routes are not shown as their own top-level spec because they are internal, callback-style, or low-level operational endpoints. Typical examples:

- callback endpoints such as `taskComplete` / `executionComplete`
- internal proxy or transport endpoints
- low-level device-control helper routes (`/server/control/*`, `/server/action/*`, `/server/web/*`, `/server/stream/*`)
- agent/MCP/benchmark tooling that follows a different interaction model than standard app APIs

If one of those route families becomes a user-facing API surface, add a dedicated grouped spec for it.

## Manual Update Checklist

When adding a new user-facing `/server/*` route family:

1. Decide which existing spec should own it.
2. If it does not fit an existing spec, create a new grouped spec in `docs/api/specs/`.
3. Add the new spec to `frontend/src/pages/ApiDocumentation.tsx`.
4. Run `python3 scripts/generate_api_docs.py`. Note: `redoc-cli` was intentionally removed from
   `frontend/package.json` (31 npm vulnerabilities via transitive deps, see `b37bd2f85`) — the
   script now falls back to a one-off `npx --yes redoc-cli@0.13.21` (needs network access, adds
   nothing to `frontend/package.json`/lockfile). Don't reinstall it as a devDependency.
5. Run `cd frontend && bash scripts/copy-docs.sh`.

## Review Rule

Before shipping new backend API routes, do a quick scan of `backend_server/src/routes/` and confirm that every new user-facing route is represented in one of the grouped specs above.

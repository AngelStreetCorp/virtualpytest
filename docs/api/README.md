# API Contracts

Server API contracts for VirtualPyTest.

## Contents

- `specs/` OpenAPI YAML specs (source contracts)
- `docs/` Rendered HTML documentation generated from specs
- `interactive.html` Swagger UI shell (served in frontend at `/docs/api/interactive.html`)

## Scope

- Public server contract only (`/server/*`)
- Backend host internals are intentionally excluded
- Coverage and maintenance notes: [COVERAGE.md](COVERAGE.md)

## Interactive Testing

Use the interactive shell to execute requests with browser-side prefilled values:

- `/docs/api/interactive.html?spec=/docs/api/specs/server-core-system.yaml&server_url=https://your-server.example.com&team_id=team_123`

Interactive profile fields:

- `server_url`
- `team_id`
- `JWT_TOKEN`
- `host_name`
- `device_id`

Environment storage model:

- `prod` / `dev` are browser-side API doc profiles, not backend server `.env` variables
- Saved in browser localStorage key `vpt_api_envs_v1`
- The API docs URL can prefill the active profile via query params such as `server_url`, `team_id`, `JWT_TOKEN`, `API_KEY`, `host_name`, and `device_id`

## Auth Notes

- The interactive shell injects `Authorization: Bearer <token>` only when `JWT_TOKEN` is set in the active browser profile
- Standard `/server/*` endpoints run without frontend JWT in open mode
- Frontend JWT becomes required only when `ENFORCE_FRONTEND_JWT=true` and `SUPABASE_JWT_SECRET` is configured
- OpenAPI parameter examples are intentionally generic; live interactive prefills come from the browser profile, not from backend env substitution

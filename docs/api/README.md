# API Contracts

Server API contracts for VirtualPyTest.

## Contents

- `specs/` OpenAPI YAML specs (source contracts)
- `docs/` Rendered HTML documentation generated from specs
- `interactive.html` Swagger UI shell (served in frontend at `/docs/api/interactive.html`)

## Scope

- Curated and generated Backend Server route specs (`/server/*`)
- Generated Backend Host route spec (`/host/*` and host health alias)
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

## Sync OpenAPI Specs to Postman

`scripts/generate_api_route_specs.py` generates inventory specs from registered Flask routes.
`scripts/sync_postman_openapi.py` imports the curated `server-*.yaml` specs as collections in
the public Postman workspace. The generated Server inventory includes registered Server routes;
the separate Host inventory remains in the API reference but is not published in this workspace.
Generated inventories include declared route/method pairs; consult the handler for exact request
and response schemas.

The shared public workspace is [VirtualPyTest on Postman](https://martian-zodiac-279215.postman.co/workspace/virtualpytest~4e7a465c-a542-4440-8903-48787f03942a) (workspace ID `4e7a465c-a542-4440-8903-48787f03942a`). To sync it, the script reads `POSTMAN_API_KEY` from the process environment or the project `.env`. The key is maintainer-only and must never be committed or sent to the frontend. Preview first, then apply:

```bash
python3 scripts/generate_api_route_specs.py
python3 scripts/sync_postman_openapi.py --workspace-id 4e7a465c-a542-4440-8903-48787f03942a
python3 scripts/sync_postman_openapi.py --workspace-id 4e7a465c-a542-4440-8903-48787f03942a --replace-managed --prune-managed --apply
python3 scripts/verify_postman_openapi_sync.py --workspace-id 4e7a465c-a542-4440-8903-48787f03942a
```

When specs change, use `--replace-managed --apply` to replace script-managed collections only.
For a route change, run the generator first.

The verifier compares registered Server route-method pairs with the specs and imported collection requests. `--prune-managed` removes only previously tracked collections whose specs are no longer part of the public Server API set (including the former Host collection); untracked collections are left alone. The verifier requires the same maintainer API key and local manifest. The script stores a gitignored `.postman_sync_manifest.json`; keep it between runs so it can replace only collections managed by this sync. See the [Postman integration guide](../integrations/postman.md) for workspace access and configuration details.

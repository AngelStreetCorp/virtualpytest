# API Coverage

The public Postman workspace combines human-written Server OpenAPI specs with a generated
Backend Server route inventory. The curated specs provide richer examples for common workflows;
the generated inventory ensures registered Server route and HTTP method pairs are present even
when a handler lacks a full OpenAPI contract. The separate Backend Host inventory remains in the
API reference but is not part of this public workspace.

## Sources

- Backend Server core routes: `backend_server/src/app.py` registration list and route blueprints
- Backend Host core routes: `backend_host/src/routes/registry.py` and route blueprints
- Optional feature routes: enabled `features/*/manifest.json` packages with service route modules
- Curated OpenAPI specs: `docs/api/specs/`
- Postman importer: `scripts/sync_postman_openapi.py`

## Generate And Sync

After changing or adding routes, regenerate route inventories and sync the specs:

```bash
python3 scripts/generate_api_route_specs.py
python3 scripts/sync_postman_openapi.py --workspace-id 4e7a465c-a542-4440-8903-48787f03942a
python3 scripts/sync_postman_openapi.py --workspace-id 4e7a465c-a542-4440-8903-48787f03942a --replace-managed --prune-managed --apply
python3 scripts/verify_postman_openapi_sync.py --workspace-id 4e7a465c-a542-4440-8903-48787f03942a
```

The sync and verifier read `POSTMAN_API_KEY` from the shell environment or project `.env`. Keep this maintainer credential private. The verifier confirms the generated specs and remote managed collections cover the current registered route/method inventory.

The route generator writes:

- `server-additional-routes.yaml`: registered Backend Server route/method pairs not already in curated specs
- `host-backend-host-routes.yaml`: registered Backend Host route/method pairs, including feature routes

The generated Server inventory includes the `/server/<path:endpoint>` proxy route. That wildcard
documents the proxy contract. Direct Backend Host routes are inventoried separately and excluded
from the public Postman workspace.

## Scope And Limits

The generated inventory reflects routes declared on registered Flask blueprints and the Host
health alias. Optional feature routes are included when their feature manifest exists, unless
the generator runs with that feature listed in `DISABLED_FEATURES`. The Host inventory follows
`HOST_TYPE`; runner-specific deployments expose a smaller registry than a full host.

Generated path parameters and simple `request.args.get()` query names are inferred from source.
Payloads and response schemas are generic; use the handler source for their exact contract.
Keep curated specs for important flows and add request/response detail there when those APIs
need polished examples. The inventories make endpoint discovery complete, but do not replace
contract review.

Current route counts are printed by `scripts/generate_api_route_specs.py` and are based on
registered route/method declarations, not generated OPTIONS/HEAD behavior.

# Postman configuration

VirtualPyTest connects to the shared [VirtualPyTest Postman workspace](https://martian-zodiac-279215.postman.co/workspace/virtualpytest~4e7a465c-a542-4440-8903-48787f03942a). The public workspace contains curated API collections and generated Backend Server route inventories. Backend Host routes are a separate service boundary and are not published in this workspace. Its public workspace ID is `4e7a465c-a542-4440-8903-48787f03942a`.

## Configure the VirtualPyTest app

1. Set `POSTMAN_API_KEY` in the backend server's private environment (for example, its ignored `.env`). This credential lets the backend read collection definitions from Postman. Never commit it or expose it in frontend code.
2. Copy `backend_server/config/postman/postman_config.json.example` to `backend_server/config/postman/postman_config.json`. The example already points to the shared workspace; do not replace it with a personal workspace.
3. Restart the backend server and refresh the Postman page in VirtualPyTest.

VPT users do not need their own Postman API key. Users granted `plugins.postman:view` can browse the shared collections and create environments in their browser. The runner sends requests directly from the user's browser to the selected backend URL; it does not proxy API requests through this VPT server. `team_id` is an optional request variable, not a Postman workspace or user ID.

## Configuration format

`postman_config.json` is the supported configuration file. It identifies the shared workspace. The legacy `environments` list is empty in the sample because runner environments are private to each user's browser. The checked-in `.example` file is the canonical sample. Its workspace section is:

```json
{
  "id": "workspace-virtualpytest",
  "name": "VirtualPyTest API",
  "workspaceId": "4e7a465c-a542-4440-8903-48787f03942a",
  "description": "Shared VirtualPyTest API collections",
  "postmanUrl": "https://martian-zodiac-279215.postman.co/workspace/virtualpytest~4e7a465c-a542-4440-8903-48787f03942a"
}
```

Environment profiles are private to the browser that created them. Set the environment name, Backend Server URL, and optional team ID from **Configure target** in the in-app runner. The URL and team ID are saved in that browser's local storage. An optional user Bearer JWT stays in page memory and is not saved. A matching Supabase session for the selected target can be used automatically.

Do not enter the server's `API_KEY` (`X-API-Key`) as a user credential. That shared key is reserved for trusted service-to-service calls and may receive service-level permissions. The runner sends a user JWT when available and never sends that service key. Public/open-mode endpoints may accept browser requests without a JWT, depending on the target server's auth posture.

When the target backend is on another origin, it must include the VirtualPyTest app origin in `CORS_ALLOWED_ORIGINS`. CORS only controls browser access; it does not authenticate Postman Desktop, curl, or other direct API clients. Use the target server's JWT/user authorization for protected requests.

## Keep the public collections in sync

The public workspace is generated from the curated `server-*.yaml` specs in `docs/api/specs/`. To cover newly registered Server routes and replace managed collections, run from the repository root:

```bash
python3 scripts/generate_api_route_specs.py
python3 scripts/sync_postman_openapi.py --workspace-id 4e7a465c-a542-4440-8903-48787f03942a
python3 scripts/sync_postman_openapi.py --workspace-id 4e7a465c-a542-4440-8903-48787f03942a --replace-managed --prune-managed --apply
python3 scripts/verify_postman_openapi_sync.py --workspace-id 4e7a465c-a542-4440-8903-48787f03942a
```

Set `POSTMAN_API_KEY` in the shell or project `.env` before syncing. The first sync command previews changes; `--apply` writes them to Postman. Keep the gitignored `.postman_sync_manifest.json` between runs. The verifier checks that the OpenAPI specs and imported requests match registered Server route/method pairs. See [API coverage](../../../docs/api/COVERAGE.md) for what generated route inventories do and do not describe.

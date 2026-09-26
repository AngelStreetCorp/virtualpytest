# Postman API collections

VirtualPyTest publishes its API collections in the [VirtualPyTest Postman workspace](https://martian-zodiac-279215.postman.co/workspace/virtualpytest~4e7a465c-a542-4440-8903-48787f03942a). The workspace ID is `4e7a465c-a542-4440-8903-48787f03942a`.

## What is included

The workspace contains curated collections with workflow examples and a generated inventory for registered Backend Server routes. Direct Backend Host routes belong to a separate service boundary and are excluded. The generated Server inventory covers declared route and HTTP method pairs, including enabled feature routes. Request and response schemas are generic where handlers do not have a curated OpenAPI contract; consult the handler or add detail to the corresponding OpenAPI spec for exact behavior.

The generated specs and Postman requests are synchronized with `scripts/generate_api_route_specs.py` and `scripts/sync_postman_openapi.py`. See [API coverage and sync](../api/COVERAGE.md) for the complete update and verification procedure.

## Browse from VirtualPyTest

Users with the `plugins.postman:view` permission can browse the shared collections in VirtualPyTest and run selected requests against a backend they choose. Configure one or more environments in the runner with a backend URL and optional team ID. Profiles are stored in that browser; an optional bearer JWT stays in page memory and is not saved. Requests go directly from the browser to the selected Backend Server. Direct Backend Host service routes are not shown.

The configured Postman workspace ID is public. A maintainer's Postman API key is needed by the backend to fetch collection data, but users do not need personal Postman API keys. Keep `POSTMAN_API_KEY` in the backend server's private environment and out of frontend code and committed files. The shared service `API_KEY` (`X-API-Key`) is not a user token and must not be entered in a runner environment.

To configure a deployment, set `POSTMAN_API_KEY` in the backend server's private environment and copy `backend_server/config/postman/postman_config.json.example` to `backend_server/config/postman/postman_config.json`. The example already names the shared workspace. Each user then configures their own backend URL and optional team ID in the in-app runner. For protected APIs, the runner uses a user JWT for that target; never use the server/host service `API_KEY`. A cross-origin target must allow the app's origin in `CORS_ALLOWED_ORIGINS`. CORS is a browser rule, not an API firewall; direct clients still need normal API authentication. Detailed setup instructions are in `backend_server/config/postman/README.md` in the source repository.

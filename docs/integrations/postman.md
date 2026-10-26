# Postman API collections

VirtualPyTest has ready-made API collections in Postman. They show how to call the platform, and they cover every server route. You can open them in the [VirtualPyTest Postman workspace](https://martian-zodiac-279215.postman.co/workspace/virtualpytest~4e7a465c-a542-4440-8903-48787f03942a).

<div data-technical>

The workspace ID is `4e7a465c-a542-4440-8903-48787f03942a`.

</div>

## What is included

The workspace has two kinds of collection. Some are hand-made examples that walk through common workflows. The others are generated from the list of server routes. Only the Backend Server routes are included. The Backend Host routes are a separate service and are left out.

Each generated route shows its HTTP method. The request and response shapes are generic when the code has no detailed contract. For the exact behaviour, read the route handler, or add detail to the matching OpenAPI spec.

<div data-technical>

The generated specs and Postman requests are kept in sync by `scripts/generate_api_route_specs.py` and `scripts/sync_postman_openapi.py`. The declared route and method pairs include the enabled feature routes. See [API coverage and sync](../api/COVERAGE.md) for the full update and check steps.

</div>

## Run requests from VirtualPyTest

Users with the `plugins.postman:view` permission can browse the shared collections inside VirtualPyTest. They can also run selected requests against a server they choose.

To do this, add one or more environments in the runner. Each environment has a backend address and, optionally, a team ID. The environments are saved in your browser. A login token (JWT) is optional. It is kept only while the page is open and is never saved. Requests go straight from your browser to the Backend Server you picked. Host service routes are not shown.

You do not need a personal Postman account or key. The backend needs a Postman key from a maintainer to load the collections, and that key stays on the server.

<div data-technical>

- The Postman key is `POSTMAN_API_KEY`. It lives in the backend server's private environment. Never put it in frontend code or committed files.
- The shared service `API_KEY` (sent as `X-API-Key`) is not a user token. Do not type it into a runner environment.
- For protected APIs, the runner uses a user JWT for that target. Never use the server or host `API_KEY`.
- A cross-origin target must allow the app's origin in `CORS_ALLOWED_ORIGINS`. CORS is a browser rule, not an API firewall. Direct clients still need normal API authentication.

</div>

## Set it up on a server

An admin does this once for each deployment. Then each user adds their own backend address in the runner.

<div data-technical>

1. Set `POSTMAN_API_KEY` in the backend server's private environment.
2. Copy `backend_server/config/postman/postman_config.json.example` to `backend_server/config/postman/postman_config.json`. The example already names the shared workspace.
3. Each user sets their backend URL and optional team ID in the in-app runner.

Detailed setup instructions are in `backend_server/config/postman/README.md` in the source repository.

</div>

# BUG-0769 — Every Run page loads its script-to-server index with a request that has no team_id, so it always answers 400 and the index stays empty

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0769                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                       |
| Area      | frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding TESTER-01, CHAOS-01, in `docs/tasks/QA-CHAOS-findings.md`, `docs/tasks/QA-TESTER-findings.md`); reproduced against the live app.

- **Page / route:** /run/tests and every other Run tab (also the legacy /test-execution/* routes)
- **Viewport / theme:** 1440 px, dark and light

Steps to reproduce:

1. Open Test > Run Tests (or Build, Monitor, Schedule, Deployments).
2. Open the browser network panel and filter for `listExecutables`.
3. Read the request and the response.

**Expected:** The executable list loads, as it does from the Campaigns tab, so each script can be resolved to the server that hosts it.

**Actual:** `GET /server/campaigns/listExecutables` is sent with no `team_id` and answers `400 {"error":"team_id is required"}` on every load of all ten Run routes. The hook swallows the error (`if (!res.ok) return []`), so the script-to-home-server index is always empty. In single-server mode the fallback hides it. In "All servers" mode the Run page has no home server for a script: TESTER-01 measured the script analysis falling back to the primary server (answers 200, right by luck today), while CHAOS-01 traced the `__all__` sentinel being turned into the URL `http://__all__/server/script/analyze`. The two finders disagree on which fallback is hit; both agree on the 400 and the empty index.

Evidence:

- [tester-01-run-page-400-listexecutables.png](../tasks/qa-evidence/tester/tester-01-run-page-400-listexecutables.png)
- [desktop-dark-test-execution-run-tests.jpg](../tasks/qa-evidence/chaos/desktop-dark-test-execution-run-tests.jpg)

## Root cause

`frontend/src/hooks/allServer/useScriptServerUrl.ts:56` builds the URL by hand instead of through the shared URL helper, which appends `team_id`. Server side: `backend_server/src/routes/server_campaign_routes.py:81-83`. The other two Run-page calls (`RunTests.tsx:510`, `CampaignSelector.tsx:109`) do carry `team_id`.

Two defects sat on that line:

1. The URL was `${serverUrl}/server/campaigns/listExecutables`, with no `team_id`, so the route answered `400 {"error":"team_id is required"}` on every load of all ten Run routes. The hook swallowed the error (`if (!res.ok) return []`), so the script-to-home-server index was always empty.
2. The `__all__` "All servers" sentinel could reach the URL builder. When the index was empty, `serverUrlFor()` returned `null` and the caller fell back to `selectedServer` — which in "All servers" mode is the literal string `__all__` — and the request went to `http://__all__/server/script/analyze` (the URL CHAOS-01 traced). The URL builder now maps the sentinel to the configured default server, exactly like `getServerBaseUrl()` already did for the socket.

## Fix

`frontend/src/hooks/allServer/useScriptServerUrl.ts` — the request is built with `buildServerUrlForServer(serverUrl, '/server/campaigns/listExecutables')`, the shared helper that appends `team_id` and keeps it idempotent. The helper takes the server URL as an argument because this hook fans out over every eligible server, not over the selected one.

`frontend/src/utils/buildUrlUtils.ts` — `buildServerUrlForServer()` refuses the `__all__` sentinel and falls back to `getServerBaseUrl()` (the configured default server), so no caller can build a request against a host named `__all__`.

## Verification

Reproduced against the live app before the fix:

```
GET https://virtualpytest.angelstreet.io/server/campaigns/listExecutables
400 {"error":"team_id is required","success":false}

GET https://virtualpytest.angelstreet.io/server/campaigns/listExecutables?team_id=<team>
200 {"campaigns":[...]}
```

Regression tests (red before the fix, green after):

- `tests/frontend/allServer/useScriptServerUrl.test.ts` — "requests listExecutables with a team_id so the route does not answer 400" and "indexes the scripts the route returns once team_id is carried" (the second one fakes the route's 400 when `team_id` is missing, and fails on the empty index without the fix).
- `tests/frontend/buildUrlUtils.test.ts` — "never builds a request against the `__all__` sentinel (BUG-0769)".

With the source reverted, 3 of the 21 tests in the two files fail; with the fix, all 21 pass. The suites that share the changed helper (`RunTests`, `useRowServerUrl`, `dispatchForRow`, `ServerManagerProvider`, `Heatmap`) also pass: 24 tests.


# BUG-0472 — DOM report signed URL 400s because the frontend omits `team_id`

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0472                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium (DOM report is the primary way to inspect captured screens) |
| Area      | frontend Interface page · `apiClient` vs `buildServerUrl`   |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

After BUG-0459's fix landed, clicking "DOM report" on
`virtualpytest.angelstreet.io/configuration/interface` produces:

```
GET https://virtualpytest.angelstreet.io/server/userinterface/domReport/url?userinterface=stb_tv 400 (Bad Request)
[@component:UserInterface] Error opening DOM report: Error: userinterface and team_id are required
```

The browser devtools show only `userinterface=stb_tv` in the query string — no `team_id`.

## Root cause

The new `openDomReport` helper called
`api.get('/server/userinterface/domReport/url?userinterface=…')` directly. `apiClient`
(`frontend/src/utils/apiClient.ts:45`) does **not** auto-append `team_id`; the
project convention is that callers wrap the path in `buildServerUrl`
(`frontend/src/utils/buildUrlUtils.ts:88-117`), which strips any pre-existing `team_id`
and re-appends `team_id=${APP_CONFIG.DEFAULT_TEAM_ID}` (a constant from
`frontend/src/config/constants.ts:54`).

The original `window.open(buildServerUrl('/server/userinterface/domReport?…'))` flow
worked because `buildServerUrl` added `team_id` for free. The new fetch path dropped
that wrapping, and the route's
`if not ui_name or not team_id: return jsonify({…}), 400` (`server_navigation_trees_routes.py:1814-1815`)
fires before the new "missing UI" check at 1817.

This is a self-inflicted follow-up to BUG-0459 — same component, same feature, just a
different missing parameter.

## Fix

`frontend/src/pages/UserInterface.tsx:466-485` — wrap the URL in `buildServerUrl`
before handing it to `api.get`, and restore the `import { buildServerUrl } from
'../utils/buildUrlUtils'` that the original implementation used (and that the
replacement had stripped as "unused" before this fix). The resulting request is
`/server/userinterface/domReport/url?userinterface=stb_tv&team_id=7fdeb4bb-…` —
exactly what the route expects.

## Why the pre-merge self-review missed it

The "buildServerUrl" import was dropped during the BUG-0459 edit because the only
remaining caller was the menu item that was being replaced; the new helper that took
its place looked complete. The new helper actually needed it too — `apiClient` does
not append `team_id`. `tsc --noEmit` accepts both because `team_id` is optional from
the route's side (just answered with 400 at runtime). A unit test that actually
invokes the new helper against a running server (or that asserts the URL it builds
contains `team_id=`) would have caught it; `test_dom_report_url_requires_params`
asserts the route's response to a bare GET, which is the very failure mode the
frontend just produced.

## Verification

- After the deploy: open `https://virtualpytest.angelstreet.io/configuration/interface`,
  click "DOM report" on any row — the new tab opens on
  `https://virtualpytest.angelstreet.io/virtualpytest/navigation/<safe>/dom_report.html?X-Amz-…`
  (signed URL via the public proxy).
- `cd frontend && ./node_modules/.bin/tsc --noEmit` clean.
- Devtools network tab on the "DOM report" click shows status 200 with a body of
  `{"success":true,"url":"…"}`.

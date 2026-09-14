# BUG-0049 — `GET /server/campaigns/results` always 500s (KeyError on response shape)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0049                                                     |
| Reported  | 2026-09-06                                                   |
| Status    | Closed                                                        |
| Severity  | Low (no known caller currently hits this route — see Root cause) |
| Area      | `backend_server/src/routes/server_campaign_execution_routes.py` |
| Fixed in  | build 8713                                                   |
| Commit    | `e0b95183c`                                                   |

---

## Symptom

`GET /server/campaigns/results?team_id=<id>` returns `500 Internal Server Error` on every call
that supplies a `team_id`, regardless of query params or data present, e.g.:

```
GET /server/campaigns/results?team_id=00000000-0000-0000-0000-000000000001
→ 500 {"success": false, "error": "..."}
```

## Root cause

`get_all_campaign_results()` (`server_campaign_execution_routes.py:476-491`) builds its response
from `results['campaign_results']` and `results['count']`, but the function it calls —
`get_campaign_results()` in `shared/src/lib/database/campaign_executions_db.py:225` — only ever
returns `{'success': True, 'data': [...]}` on success (or `{'success': False, 'error': ...}` on
failure). It never sets `campaign_results` or `count`. So any successful call raises a `KeyError`
building the response, which `@handle_route_exceptions` turns into a 500 — the route always failed
whenever `get_campaign_results` itself succeeded.

Separately, this route (`/server/campaigns/results`, defined in
`server_campaign_execution_routes.py`) is distinct from the endpoint the frontend actually calls
for campaign results — `/server/campaign-results/getAllCampaignResults`
(`server_campaign_results_routes.py`), used by `useCampaignResults.ts` / `TestReports.tsx`. No
frontend caller of `/server/campaigns/results` was found, so this bug had no observed user impact,
but the route was silently broken for any future/external caller.

## Fix

`server_campaign_execution_routes.py` — build the response from the actual shape
`get_campaign_results()` returns:

```python
return jsonify({
    'success': True,
    'campaign_results': results['data'],
    'count': len(results['data'])
}), 200
```

## Verification

- Added `test_get_all_campaign_results_returns_expected_shape` to
  `tests/backend_server/test_campaigns.py`: asserts `200`, `success: true`, `campaign_results` is
  a list, `count` is an int equal to the list length.
- `python -m py_compile` clean on both changed files.

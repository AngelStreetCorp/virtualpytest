# BUG-0416 — Test Reports showed a raw Cloudflare 502 page on the RPI1 server

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0416                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | shared / database, frontend                                  |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Test → Report → Test Reports, with the RPI1 server (`<pi-server-host>`) selected, showed
`{'message': 'JSON could not be generated', 'code': 502, … 'details': b'<!DOCTYPE html>… 502: Bad gateway…`
instead of the table. `GET /server/script-results/getAllScriptResults` returned 500 on every call
from that server. The same call on the main server (`virtualpytest.angelstreet.io`, VM .103)
returned 200 in ~70 ms. The DB VM was healthy (load 0.3, swap 40 %, disk 74 %).

## Root cause

TASK-42 (`6bfd604f9`) added `_attach_labels()` in `shared/src/lib/database/script_results_db.py`:
after the page of results, it reads their labels with `in_('script_result_id', ids)` in chunks of
**100** uuids (same in `labels_for_entities()` and `fetch_script_results_by_ids()` in
`run_management_db.py`).

PostgREST echoes the full query string in a `Content-Location` response header. With 100 uuids
that header is ~4.6 KB. The RPI1 server reaches Supabase through the public URL
(`SUPABASE_URL=https://virtualpytest.angelstreet.io/supabase`) → Cloudflare → proxy nginx
(`location ~ ^/supabase/(rest|…)/v1/`, default 4 KB `proxy_buffer_size`) → Kong. nginx rejects
the oversized upstream header and Cloudflare returns its 502 page. Measured from the RPI1 server
with random uuids: 80 ids → 200 (`Content-Location` 3669 bytes), 85+ ids → 502. A 401 (no
`Content-Location`) passes at any length, which is why anon-key tests looked fine. The main server
calls Kong directly on the LAN (`http://192.168.x.102:54321`), so it was not affected.

The frontend then put the server's error text — the whole HTML page — into the page.

## Fix

- `IN_FILTER_CHUNK = 50` in `script_results_db.py`, used by `_attach_labels()` and by the two
  chunked reads in `run_management_db.py` (50 uuids ≈ 2.4 KB of query string).
- `useScriptResults.getAllScriptResults` shows a short message when the server error contains
  HTML, and caps other server errors at 300 characters; the full text stays in the console log.
- Test: `test_labels_for_120_results_stay_under_the_proxy_url_limit` in
  `tests/backend_server/test_run_management_db.py`.

## Verification

After a server deploy on the RPI1 server, Test Reports with that server selected lists runs, and
`GET https://<pi-server-host>/server/script-results/getAllScriptResults?team_id=…` returns
200.

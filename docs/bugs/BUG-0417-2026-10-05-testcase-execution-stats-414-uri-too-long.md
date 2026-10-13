# BUG-0417 — Test case run counts failed with "414 URI too long" on every list

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0417                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | shared / database, backend_server                            |
| Fixed in  | Unreleased                                                   |
| Commit    | `284f93609`                                                  |

---

## Symptom

The main server log (`vpt-server` on VM .103) printed, 222 times in 6 hours on 2026-10-05:

```
[@testcase_db] Warning: Failed to fetch execution stats: {'message': 'JSON could not be generated',
'code': 414, 'hint': 'Refer to full message for details', 'details': "b'URI too long\\n'"}
```

Every call to `list_testcases()` hit it: `GET /server/testcase/list` (Test Case Editor "Load test
case" dialog, Campaign Builder toolbox, AI Agent chat), `GET /server/executable/list` (Run Tests,
Build Campaigns, the executable picker) and the analytics quality catalog. The warning is
swallowed, so every test case came back with `execution_count: 0` and
`last_execution_success: null`. No page renders those two fields today (only `TestCaseSelector`
declares them), so nothing looked wrong on screen; the cost was one failed database round trip
per list call and a log full of warnings.

## Root cause

`list_testcases()` in `shared/src/lib/database/testcase_db.py` reads the run stats with one
`script_results` query filtered by `in_('script_name', <every test case name>)`. supabase-py puts
that list in the request URL. The team has 201 test cases whose names add up to 10,191 characters
(longest 77), so the URL is over 10 KB once quoted and encoded, and the Supabase gateway in front
of PostgREST answers 414. The sibling query on the same page, `in_('testcase_id', <201 uuids>)`
for version numbers (~7.5 KB), still passed, so the limit sits between the two — the uuid query
was a few more test cases away from failing too.

Same pattern as [BUG-0416](BUG-0416-2026-10-05-test-reports-502-on-rpi1-server-long-label-lookup.md)
(there the 4 KB response-header buffer of the public proxy gave a 502 at ~85 uuids).

## Fix

- New `shared/src/lib/database/in_filter.py`: `IN_FILTER_CHUNK = 50` and
  `chunked_in(query_fn, values, size=IN_FILTER_CHUNK)`, which runs one query per 50 values and
  returns all rows. `IN_FILTER_CHUNK` moved here from `script_results_db.py`.
- `list_testcases()` uses it for both the stats and the version queries.
- The same helper now backs every read whose id list grows with the data:
  - `campaign_db` campaign run stats (same pattern as test cases),
  - `folder_tag_db.get_executable_tags_bulk` (all scripts and test cases),
  - `navigation_trees_db`: root trees per interface, trees with nodes, full trees
    (were chunked at 100 uuids, ~3.7 KB — over the BUG-0416 proxy limit), `get_nodes_batch`,
  - `navigation_metrics_db` / `execution_results_db` node and edge metrics of a tree, and the
    tree / edge / node / report lookups of `get_execution_results`,
  - `campaign_executions_db` linked script results (were 200 and 50 per batch),
  - `report_snapshots_db.get_script_summaries`, the label lookups in
    `backend_server/src/services/analytics/report_query.py` and `services/sharing/snapshot.py`
    (up to 500 run ids), and the script-result lookup in `server_deployment_routes.py`,
  - the three existing BUG-0416 loops in `script_results_db.py` / `run_management_db.py`.
- Tests: `tests/backend_server/test_in_filter_chunking.py` (the fake client raises 414 above
  50 values; the 200-test-case stats test fails on the old code) and the BUG-0416 test in
  `tests/backend_server/test_run_management_db.py`.

Writes and deletes that already chunk (navigation tree wipe/publish) are unchanged.

## Verification

After a server deploy on .103:
`sudo journalctl -u vpt-server --since -1h | grep -c "Failed to fetch execution stats"` is 0, and
`GET /server/testcase/list` returns non-zero `execution_count` for test cases that have run.

## Follow-up: row cap (2026-10-05)

PostgREST on our stacks answers at most `PGRST_DB_MAX_ROWS=1000` rows per request (checked on the
database VM). The stats are counted in Python from the returned rows, so a chunk of 50 test cases with
more than 1,000 runs would still undercount. `chunked_in` now reads each chunk in pages of 1,000 with
`.range()` (`MAX_ROWS_PER_REQUEST` in `shared/src/lib/database/in_filter.py`); callers must not add their
own `.limit()`/`.range()`. Test: `test_chunked_in_pages_past_the_postgrest_row_cap` (fails on the
unpaged helper). Two test fakes gained the `.range()` method the real client has.

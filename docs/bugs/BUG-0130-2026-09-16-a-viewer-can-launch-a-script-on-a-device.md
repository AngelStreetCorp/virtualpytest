# BUG-0130 — A viewer can launch a script on a device

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                   |
|-----------|-------------------------------------------------------------------------|
| ID        | BUG-0130                                                                |
| Reported  | 2026-09-16                                                              |
| Status    | Fixed (pending deploy)                                                  |
| Severity  | High (authorization gap: a read-only account can drive shared hardware)  |
| Area      | `backend_server/src/routes/server_script_routes.py`                     |
| Fixed in  | build 9151                                                              |
| Commit    | TBD                                                                     |

---

## Symptom

`POST /server/script/execute` accepts a request from any authenticated caller, including an
account whose role is `viewer` — a role whose entire permission set is `*:view`. The viewer
cannot see the Run Tests controls in the UI, but the route behind them is open to anyone who
calls it directly, and running a script takes a real device.

## Root cause

The route carried no authorization decorator at all:

```python
@server_script_bp.route('/script/execute', methods=['POST'])
def execute_script():
```

The permission exists and is enforced elsewhere: `/server/testcase/execute` and its siblings
carry `@require_permission('execution.run:run_test')`, and the role matrix
(`auth_middleware.py`) grants that to `tester` and withholds it from `viewer`. The script
launcher — the thing the Run Tests page actually calls — was never wired to it.

**Why nothing caught it:** `tests/backend_server/test_permissions.py::test_viewer_cannot_run_test`
asserts exactly this and has existed all along. It skipped itself on every run, because its
`host_name` fixture read `/server/server-manager/hosts`, which is not a route — it falls into
the `auto_proxy` catch-all and answers 400, so the helper returned `""` and the test skipped
with "No host_name available" on a server with five hosts registered. The skip was removed
2026-09-16 while cleaning up permanently-skipped tests, and the test then failed — for the
second reason below.

Even once it ran, the test could not have proven anything: its payload omitted `device_id` and
`script_name`, so the route answered 400 (malformed) before any authorization question, and the
assertion `status_code == 403` failed for a reason unrelated to permissions.

## Fix

- `@require_permission('execution.run:run_test')` on `/server/script/execute`. Admin and the
  shared service principal bypass the check inside the decorator, so host callbacks, dmacp and
  MCP are unaffected; `tester` holds the permission by default.
- The test now sends a complete payload, so a 403 means "denied", not "missing field".
- `_get_host_name` reads `/server/system/getAllHosts` and prefers VirtualPyTest's own device
  host over the `labox-*` fleet.

## Verification

With `VIEWER_TEST_JWT` configured, `test_viewer_cannot_run_test` must return 403 and
`TestRoleBaselines` must stay green for admin/tester (they hold the permission). After deploy,
confirm a tester can still start a run from Run Tests — the permission gate is the only new
thing between that button and the host.

# BUG-0153 — the KPI report's "Last Action" was always `N/A`

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0153                                                     |
| Reported  | 2026-09-21                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low (display only; the value was available elsewhere)        |
| Area      | `shared/src/lib/utils/kpi_report_generator.py`               |
| Fixed in  | Unreleased                                                   |

---

## Symptom

Every KPI report header, on every host, for as long as the field has existed:

```
Navigation: home_replay → replay  |  Last Action: N/A
```

The collapsible "Last Action Executed" section further down the same report showed the action
perfectly well (`Command: press_key`, `Parameters: {"key": "OK", "wait_time": 4000}`), so the
report contradicted itself.

## Cause

The header rendered `request.last_action`, which `kpi_executor` reads from the queued request
(`kpi_executor.py:371`), which `navigation_executor` populates from `step.get('last_action')`
(`navigation_executor.py:2959`).

**Nothing ever sets `step['last_action']`.** That line is the only reference to the key in the
entire navigation package — there is no assignment, in any code path, so it is always `None` and
the header always fell through to `'N/A'`.

The action was never actually missing: `action_details` is built and forwarded in the very same
request dict, one line below, and is what the "Last Action Executed" section renders.

## Fix

`_last_action_label(request)` composes the header label from what is actually present, preferring
`last_action` in case a caller ever populates it:

| input | header shows |
|---|---|
| `command=press_key`, `params.key=OK` | `press_key OK` |
| `command=launch_app`, `params.package=com.x` | `launch_app com.x` |
| `command=reboot`, no params | `reboot` |
| no `action_details` | `N/A` |

Applied to both the success and the failure report.

## Notes

The dead key is left in place rather than removed: it is forwarded through the queue file and the
request object, and a caller that does set it should still win over the derived label. What changed
is that the report no longer depends on a key nobody writes.

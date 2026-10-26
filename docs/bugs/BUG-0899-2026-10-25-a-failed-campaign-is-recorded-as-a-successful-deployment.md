# BUG-0899 — A failed campaign is recorded as a successful deployment

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0899                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend (campaign executor / deployment scheduler / host campaign routes) |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/e75-campaign-verdict`                        |

---

## Symptom

A campaign that ran to the end and failed every check was recorded in `deployment_executions`
as `status='completed'`, `success=true`, while its own `campaign_executions` row said
`success=false`. A reader of the deployments table saw a green fleet; only the campaign table
carried the truth. Measured on the live database (2026-10-25): 5,828 joined rows (2,128
deployment executions) all time, and since 2026-10-01 no `failed` deployment row at all for any
campaign that actually ran, against 210 campaigns that ended `success=false`. The async route
reported the same wrong `completed` as the running campaign's status on the dashboard.

## Root cause

`CampaignExecutor._build_success_result()` (the result for a campaign that ran to completion)
returned a hard-coded `"success": True`, while the same dictionary carried the real verdict as
`"overall_success"`. The failure path already returned `context.overall_success`. The scheduler
(`script_success = campaign_result.get('success')`) and `host_campaign_routes.execute_campaign_async`
both read `success`.

## Fix

`"success"` in that result is now `context.overall_success` — the value the campaign row already
stores — so the deployment row, the async `final_status` and the nested sync result all carry the
one verdict. The result also gains `"aborted"` (the async route and callback already read it but
this path never set it), so an aborted run keeps its `aborted` reading instead of becoming
`failed`. The sync route's envelope `success: true` still means "request handled". The campaign
row and how a script's own success is judged are unchanged.

Rows already written stay as they are; no backfill.

# scripts/nightly_campaigns

Phase 2 helpers for TASK-63 — every nightly script / virtual script / test
case runs once per night on the AngelStreet internal team.

| Script | What it does |
|---|---|
| `build_layout.py` | Reads the live platform state across every backend server and writes `layout.json` with one bucket per (category × host × device). Skips QualiAI (per owner scope rule) and keeps only one `host-clone-1` copy (Awesomation) to avoid the cross-server scheduler collision. Excludes 146 empty-UI testcases per owner Q3. |
| `create_campaigns.py` | Creates one DB campaign per bucket (and orphan campaigns for UIs without a matching device), then one recurring deployment per non-orphan campaign. Cron defaults to `30 0 * * *` UTC = 01:30 CET winter (owner Q2, DST option 1). |
| `run_once.py` | Posts `/server/deployment/run/<id>` for every nightly deployment, from the server that owns the host. Sleeps between calls to let the per-host device lock release. |
| `poll_results.py` | Polls `/server/campaign-results/getAllCampaignResults` until every nightly campaign reaches a terminal state or `deadline` elapses, writing `poll_state.json`. |

## Aware-of

- The `validate_campaign_config` helper in `shared/src/lib/database/campaign_db.py` rejects `script_type='virtual_script'` — `create_campaigns.py` works around that by creating the campaign with an empty `script_configurations` and injecting the full body via `deployment.parameters` (the scheduler reads it first when non-empty: `backend_host/src/services/deployment_scheduler.py:1398-1427`).
- Per-host device lock: when two `run_once.py` invocations hit the same `(host, device_id)` inside the lock window, the second is skipped (`backend_host/src/services/deployment_scheduler.py:1051-1062`, reason `Device host busy (recurring CRON, will retry next trigger)`). The `--wait-seconds` flag in `run_once.py` waits between calls; Phase 2 needed ~60-90 s for the longer campaigns.
- The scheduler hard-codes `timezone='UTC'` (`backend_host/src/services/deployment_scheduler.py:47,117`). DST is handled by accepting the 1-hour slip in summer (owner Q2, option 1) rather than threading a per-deployment timezone.

## A future-phase helper (not written) — model-targeted run

The owner wants a "pick a device model, click run" feature with two modes
(ALL-IN-ONE-TARGET / REPARTITION). See `docs/tasks/TASK-63-nightly-campaigns.md`
"Future phase — run on the available target feature (no code this pass)"
section for the spec. Implementation is a separate task.
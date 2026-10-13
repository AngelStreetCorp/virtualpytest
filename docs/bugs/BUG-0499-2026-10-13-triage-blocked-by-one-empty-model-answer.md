# BUG-0499 — One alert the vision model cannot read blocked the triage of every other alert

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0499                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_server / alert triage (vpt-discard-incidents)        |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

The Grafana rule "Too many incidents on a device" fired for two devices (37 and 40 incidents in the last hour) and 466
alerts of the last two days had no verdict, 356 of them older than the 6 h triage window, so they would never get one.
The worker log showed the same alert failing again and again with `empty answer from 'minimax-vlm'`, each time with a
longer pause on model calls (60 s, 240 s, 960 s, up to 3600 s).

## Root cause

The vision model sometimes returns an empty answer for one specific frame. The worker treated every failed call like a
provider outage (no credit, timeout): it paused model calls for **all** alerts and retried the same alert next cycle, which
failed the same way and doubled the pause. One unreadable alert therefore blocked the other alerts for up to an hour.
Alerts that left the 6 h window without a verdict stayed untriaged forever.

## Fix

`backend_server/src/agent/core/nightwatch_handler.py`:
- an empty or unparseable answer is a per-alert failure: no global pause; after two tries the alert is skipped as
  `[SKIP:model_empty]` and kept for a human;
- credit, timeout and HTTP errors still pause every alert (unchanged);
- alerts older than the triage window with no verdict are marked `[SKIP:expired]` (checked every 10 minutes).

### Related: two Grafana rules were noisier than the facts

- **Too many incidents on a device** counted alerts the triage had already settled (repeats of a discarded alert, alerts that
  resolved within seconds, alerts that aged out). It now ignores `[SKIP:short]`, `[SKIP:expired]` and `[SKIP:repeat]` of a discard.
- **Host stopped reporting** listed three "server" rows as stopped. A server now stores its metrics under its `SERVER_NAME`
  instead of the literal `server`, so the old series went quiet and stayed in the 3-day window. The rule skips a `server`
  series when the same server reports under another name in the last 15 minutes.

- **Platform service down** read `service_status`, which since migration `20261001f` is only a change log, so every healthy
  component looked "stale" after 3 minutes (9 false alerts, including "Discard Incident is stale" while the worker was active).
  It now reads `service_status_current`, the live heartbeat the System Service Status page uses; a renamed or retired server
  drops out after a day.
- **Script failing repeatedly** sent one alert per failing script: a dead phone failing all 13 of its scripts made 13 alerts
  (48 in all, over 4 devices). It now sends one per device, listing the scripts, and ignores a device that has not run
  anything for 2 days (the host and device-down rules cover that).

Catalog: `infra/monitoring/grafana/alerting/vpt-alert-rules.json`; both live rules were updated in place through the
provisioning API (no full `apply`, so thresholds edited in the UI and the contact point stay as they are).

## Verification

`python3 -m pytest tests/shared/test_nightwatch_triage.py -q` (empty answers do not block, two skip the alert, a credit failure
still blocks). After deploy: the worker log shows `model gave no usable answer ... (1/2)` instead of `blocked 3600s`, the
untriaged count drops (`select count(*) from alerts where check_type is null and start_time < now() - interval '6 hours'` is 0).

# GOAL-04 — Per-device health checks (mobile, STB, TV, web)

**Status:** active
**Arbitrator:** the owner

Every device in the fleet gets a periodic, device-type-aware health check — an agent
verifies the device is alive, controllable, and capturing correctly, and files
remediation tasks when it isn't.

## End state (success criteria)

- Each registered device (android_mobile, STB, TV, web/VNC) has a scheduled health
  check appropriate to its type: capture alive, control path responsive (ADB / IR /
  BLE / browser), stream healthy, reference screen reachable.
- Failures produce a diagnosis pointing at the right layer (capture / control / device
  asleep / network) — not just "device red".
- A fleet health report exists per day; degraded devices carry an open remediation task.

## Exists today / Gap

- **Exists:** 5fps capture monitoring with freeze/blackscreen/audio incident state
  machine (capture_monitor.py + detector.py, pure OpenCV); Nightwatch alert triage
  (pre-filtered, ~5–10 AI analyses/hour); ffmpeg stall watchdog; device lock/control
  lifecycle; MCP device tools (screenshot, action, device info).
- **Gap:** monitoring covers the *capture* path well but "controllable" isn't probed —
  a device can stream fine while its ADB/IR/BLE path is wedged; no per-device-type
  checklist; no daily fleet report; remediation is manual.

## Guardrails

- **The STB/device is never assumed to be the culprit** — real UE remotes always work;
  diagnose the Pi/host side (IR toy wedge, BLE bond state, btmgmt stdin wedge) before
  blaming the device.
- **SMPTE bars / tiny black JPEG (~7–14 KB) = STB asleep** — press POWER once before
  concluding capture failure. The customer's STB HOME toggles TV↔menu — press once, not
  repeatedly.
- **BLE: never click "Start Pairing" after a reboot** when the bond is intact on disk —
  use the resume path. Multiple bonded peers need the connected-peer picker.
- **Health probes must not steal control** from an active test session — check the
  device lock before any probe that takes control; skip and note, don't force-unlock.
- **IR/BLE presses are never "dropped" by transport** — a failed nav is timing,
  reference, or area; don't file transport bugs.

## Arbitration gates (always require human approval)

- Rebooting a host or device.
- Physical-intervention tasks (replug IR toy, power-cycle STB) — agent files them,
  human executes.
- Any change to the monitoring services themselves (vpt-host, vpt-monitor, ffmpeg).

## Active tasks

- [TASK-04-daily-fleet-health-report](../tasks/TASK-04-daily-fleet-health-report.md) — **done**
- [TASK-04-schedule-daily-report](../tasks/TASK-04-schedule-daily-report.md) — **done** (timer live on .103, daily 07:00 Zurich, MinIO upload)
- [TASK-04-fleet-health-db-grafana](../tasks/TASK-04-fleet-health-db-grafana.md) — **done** (fleet_health table + Grafana uid vpt-fleet-health)

## Log

- 2026-07-16 — TASK-04-fleet-health-db-grafana → done: fleet_health table (040 schema),
  script inserts per-device rows each run, Grafana dashboard vpt-fleet-health live
  (latest run + history + report links). Fleet health now checkable in Grafana.

- 2026-07-15 — TASK-04-schedule-daily-report → done: PR #1 merged, main deployed fleet-wide
  (7 targets), vpt-fleet-health.timer enabled on .103, first production run verified
  (report + MinIO presigned URL). GOAL-04 "daily fleet report" end-state partially met —
  remaining gaps: control-path probing, idle-vs-activity via last_action, remediation tasks.

- 2026-07-15 — TASK-04-daily-fleet-health-report → done (arbitrator accepted v2: Since column,
  IDLE verdict, frame-vs-incident reconciliation, --ai diagnosis). Follow-up
  TASK-04-schedule-daily-report proposed.
- 2026-07-15 — TASK-04 → in-review: `scripts/fleet_health_report.py` implemented, live run
  covered 3 hosts / 6 devices across both servers (OK 0 · DEGRADED 6 · DOWN 0 · UNKNOWN 0).
  Finding: Cloudflare edge blocks external API calls on virtualpytest.* → daily cron must
  run inside the infra. Cron scheduling proposed as next gated item.
- 2026-07-15 — TASK-04-daily-fleet-health-report approved by arbitrator (in session); work started.
- 2026-07-15 — Goal created.

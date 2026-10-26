# BUG-0792 — The Monitoring button is disabled on every browser host, so no FPS can be read there, and its tooltip names a profile (tv_lite) the host does not run

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0792                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Medium                                                       |
| Area      | frontend                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding TESTER-06, OPS-12, TESTER-04, in `docs/tasks/QA-OPS-findings.md`, `docs/tasks/QA-TESTER-findings.md`); reproduced against the live app.

- **Page / route:** /device-control > device tile > live view modal header
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open Device and click the preview of host-clone-1, host-clone-2 or labox-backend.
2. Hover the greyed-out Monitoring button in the modal header.

**Expected:** The overlay can be switched on to read FPS, freeze and network health, or the tooltip names the real profile.

**Actual:** Monitoring, Last 24h, Actions, Show Web, Timeline and Ask AI are disabled for every `host_vnc` device (`monitoring_off` lists all of them on host-clone-1, `['host']` on labox-backend), although the hosts capture at 2 to 10 fps. The tooltip always reads "Monitoring is off for this device (profile tv_lite)" while the configured profile is `pc`; no device in the lab runs `tv_lite`. labox-mobile is the only device where the overlay opens, and there it shows correct numbers (`FPS in 5 out 5`, latency 1.5 s). The `tv_lite`/"stream and control only" behaviour itself is documented (`utils/monitorProfileInfo.ts`); the defects are the invisible FPS on the hosts that run browser tests and the wrong text.

Evidence:

- [tester-06-monitoring-disabled-on-pc-profile.png](../tasks/qa-evidence/tester/tester-06-monitoring-disabled-on-pc-profile.png)
- [ops-12-monitoring-disabled-live-view.png](../tasks/qa-evidence/ops/ops-12-monitoring-disabled-live-view.png)
- [tester-04-fps-display-live.png](../tasks/qa-evidence/tester/tester-04-fps-display-live.png)

## Root cause

`frontend/src/components/rec/RecStreamModalHeader.tsx:180` hard-codes the tooltip text; the button is `disabled={!isLiveMode || monitoringOff}` (`:632`, `:179`).

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.

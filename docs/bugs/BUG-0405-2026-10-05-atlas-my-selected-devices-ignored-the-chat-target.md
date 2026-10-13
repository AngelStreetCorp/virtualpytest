# BUG-0405 — Atlas answered "my selected devices" for the whole server instead of the chat's Target

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0405                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_server (agent + analytics)                           |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Main server, build 10002, MiniMax, Target host-clone-1 selected in the Agent Chat header. Prompt "Build a canvas for my
selected devices: pass rate by device, duration trend and incidents over the last 7 days". The canvas said "Limited to the
5 host(s) of the selected server Awesomation" and listed labox-tv / labox-web_Host: the Target was ignored.

## Root cause

"my/selected/this device(s)" only relied on a router prompt line asking the model to pass `scope='current_device'`. The model
did not always comply, and nothing in the tools enforced it (unlike named devices, BUG-0355).

## Fix

Same pattern as BUG-0355. `named_devices.refers_to_selected_device` / `selected_device_state` detect whole phrases ("my selected
devices", "selected device", "my device", "this/current/the selected/the target device", "the target"; never a bare
"devices" or "by device"); `QAManagerAgent._record_named_devices` stores `refers_to_selected_device` (only when the Target is set
and on the selected server hosts, the BUG-0311 check), `selected_device` and `selected_device_foreign` per message; `ToolBridge`
injects them. `enforce_selected_device` in `analytics_tools.py` sets `scope='current_device'` on every unfiltered request
(a canvas at the top level plus each unfiltered panel) for query / render / export / create_grafana_draft, and the reply and the
artifact's scope note say "Limited to your selected device <name> (<host>)". Named devices win; an explicit device/host filter is
kept; a foreign Target keeps the visible scope and the reply says the Target is not on this server. The router prompt line now says
"always pass scope='current_device'".

## Verification

`tests/backend_server/test_atlas_selected_device.py` (phrase detection incl. negatives, render single and canvas, query, export,
draft, foreign Target, named devices win) and `test_selected_device_reference_is_recorded_per_message`. Live: suite prompt
`selecteddev` (`E2E_ONLY=selecteddev`) fails on the build before the fix and must pass after deploy.

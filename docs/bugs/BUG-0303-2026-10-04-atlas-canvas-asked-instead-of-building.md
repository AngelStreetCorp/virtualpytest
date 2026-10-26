# BUG-0303 — Atlas answered a canvas request with a question instead of building it

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0303                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — the requested canvas was not built                  |
| Area      | `backend_server/src/agent/core/manager.py`, `backend_server/src/lib/analytics/service.py` |
| Fixed in  | build 90145 |
| Commit    | see branch `task43-w4-canvas-devices`                        |

---

## Symptom

On the Pi server (36 devices, 4 hosts), "Build a canvas with 3 panels for my selected devices: pass
rate by device, KPI averages, and incidents over the last 7 days" was sometimes answered by a
question ("Which userinterface would you like to use...?", same family as "which devices?") instead of a canvas.

## Root cause

The router offers the canvas tools correctly. The model's first call used the presets
`pass_rate_by_device`, `kpi_radar`, `incidents_over_time`; `kpi_radar` needs `userinterface_name`, and the
tool answered only `Missing preset filters: ['userinterface_name']`. That dead end, with no rule in the
prompt saying what to do instead, made some runs stop and ask (live session `e064c6e9`, 16:27: asked for a
userinterface; the same prompt in `a7dd06af` recovered only after ~25 tool calls). Same shape for
`scope='current_device'` with nothing selected ("No current device is selected"). The prompt also
never said what scope applies: it listed only the first 10 of 36 devices, `Current Device` carried no
name, and nothing told the model that "my selected devices" means the Current Device (or, with none,
the visible fleet). With the device pinned, runs ignored it and charted the whole fleet without saying so.

## Fix

- Router prompt: `Current Device` gets its `device_name`; the selected device is always listed first;
  an `Analytics scope` line says what "my/selected devices" means (current device, or visible fleet when
  nothing is selected) and requires stating the scope used; a router rule forbids asking about
  devices/userinterfaces/time range when scope or defaults answer it.
- `Missing preset filters` and `No current device` errors now say "do not ask the user" and give the way
  forward (list the values, or build without the preset; retry with `scope='visible'`).

Not changed: the chat sends only one selected device (`host_name`/`device_id`), never the multi-select list.

## Verification

- `tests/backend_server/test_agent_minimax_quirks.py` (canvas prompt offers the analytics tools; prompt names
  the selected device even at position 25 of 30 and forbids asking; no-selection prompt defaults to visible)
  and `tests/backend_server/test_atlas_analytics.py::test_dead_end_errors_tell_the_model_not_to_ask_the_user`.
- Live before the fix (Pi, main code): 6 canvas runs, 2 without a device and 3 with one completed (the
  with-device runs ignored the device); 1 asked a question after the preset error. Not re-run after the fix:
  the live Pi runs main's code.

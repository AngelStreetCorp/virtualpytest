# BUG-0851 — Atlas answered "Screenshot <device>" with the page list or the host list

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0851                                                          |
| Reported  | 2026-10-23                                                        |
| Status    | Fixed (pending deploy)                                            |
| Severity  | Medium                                                            |
| Area      | backend_server (Atlas quick step) / ai                            |
| Fixed in  | build 90145 |
| Commit    | TBD                                                               |

---

## Symptom

TASK-163 baseline, read-only prompts on a live server: "Dump the UI elements of <device>", "Show me what <device> is
displaying", "Check which <model> are asleep" were answered in under a second by `get_available_pages`, and
"Screenshot <device> on <host>" by `list_hosts` — a short command answered by a tool that has nothing to do with it.

## Root cause

The quick step offers the small model at most 8 tools (the team's most used) and one escape, `ask_atlas`. When none fits, the
model still picks one, and the pick was only checked for argument validity, never for relevance. The reply is the
tool's own output, so the user got a page list instead of an answer and the full Atlas turn never ran.

## Fix

`quick_step.fits()`: an info tool (pages, docs, videos, results, KPI, hosts, device info) is accepted only when the
message has a word about its subject, and never when the message names a known device. Otherwise the quick step
refuses the pick and the normal Atlas turn runs. `tests/backend_server/test_atlas_quick_step.py`.

Second round (after-run, same day): the fast path also took `take_control` for "Take a screenshot of <device>", and the
`device-control` skill had no `capture_screenshot`, `take_control` or `release_control`, so a screenshot or
"who is controlling <device>" went looking in analytics. `fits()` now requires "control"/"lock" for `take_control` and
"release"/"free" for `release_control`; the skill gets the three tools, triggers for these short commands and a
short-command table in its prompt.

Found by TASK-163 (`docs/agent/atlas/USECASES.md`).

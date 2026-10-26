# BUG-0281 — Validate skipped the entry edge and reported a fully passing tree as failed

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0281                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — Validate never tested the entry edge and never reported success |
| Area      | `test_scripts/validation.py`, `backend_host/src/services/navigation/navigation_pathfinding.py` (`_create_validation_step`) |
| Fixed in  | build 90145 |
| Commit    | this commit                                                  |

---

## Symptom

Validate on an AI-built Android interface (Google TV, 4 screens): the 8 screen edges passed
(every tap forward, every way back) but the run was **FAILED**. Its first step, `Entry → home`,
was skipped with *"could not reposition to 'Entry'"*.

## Root cause

Before each step the script moves the device to the step's start node when it is elsewhere.
For the first step that start is the entry point, and no edge leads into the entry point, so
the move always fails. The skipped step counted as a failure.

## Fix

Validation steps now carry `is_entry_transition` (the flag pathfinding steps already had). The
script does not reposition before such a step: the entry edge's own actions (here `close_app`,
`launch_app`, tap Home) start the interface from anywhere.

## Verification

- `py_compile` passes.
- Copied to vpt-pi1 (script-only files, identical to `main`) 2026-10-04: Validate on
  `google-tv-mobile-ai` ran `Entry → home` and passed 9/9 (100 %, 179 s); it was 8/9 with Entry
  skipped before.

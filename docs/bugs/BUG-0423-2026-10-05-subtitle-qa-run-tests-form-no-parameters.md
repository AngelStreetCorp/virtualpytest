# BUG-0423 — Run Tests showed "No parameters" for subtitle_qa

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0423                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed                                                        |
| Severity  | Low                                                          |
| Area      | test_scripts / Run Tests parameter form                      |
| Fixed in  | build 90145 |
| Commit    | b3360ce34                                                    |

---

## Symptom

Picking `subtitle_qa` on the Run Tests page showed "No parameters", so `--video`, `--lang`, `--audio_json` and `--credits_from` could not be set from the form. A run through the API with the same arguments worked.

## Root cause

The form's parameter analyser reads only the first 300 lines of a script to find its `_script_args` list (contract: `_script_args` near the top). In `test_scripts/subtitle_qa.py` the list sat below line 294, past the window.

## Fix

The `_script_args` block moved to the top of `subtitle_qa.py`; `docs/agent/execution/SUBTITLE_QA.md` lists the trap. Server deploy 8d076a29.

## Verification

Run Tests on the RPI1 server, vpt-pi4 / device1, `subtitle_qa`: the form lists the arguments, and the run filmed for promo video 21 (script result `e653eeee-9abf-49ba-baf9-b16d9f192e35`) was started from it and passed.

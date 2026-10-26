# BUG-0685 — A script run queued behind another job lost its --userinterface flag and stopped at argparse

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0685                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                       |
| Area      | backend_host deployment scheduler |
| Fixed in  | build 90145 |
| Commit    | `8e7e681c5`                                                  |

---

## Symptom

`execute_script(validation.py, parameters="--userinterface=<ui>")` passed on an idle device, but when the device was busy and the run was
queued, it ended with "Unknown argument(s) for validation: <ui>" ("crashed before it started"). Seen on every TASK-135 scoring run that hit a
busy device.

## Root cause

`/server/script/execute` queues a busy-device run as a one-shot deployment with the parameters string as given. The host scheduler rebuilt
the argv: it put `userinterface_name` first as a bare positional, then filtered the parameters with a loop that treated every `--x` token as
a flag expecting the next token as its value. `--userinterface=<ui>` is followed by `--host`, so it was dropped as "a flag without value".
The script got `<ui> --host H --device D`, and argparse rejected the positional.

## Fix

`backend_host/src/services/deployment_scheduler.py`: the argv is built by `build_script_params(dep)`. `--flag=value` tokens are kept whole,
and the positional userinterface is added only when the parameters do not name one already.

## Verification

`tests/backend_host/test_deployment_scheduler_params.py`. Live: a validation queued behind another job runs with its userinterface.

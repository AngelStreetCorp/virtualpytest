# BUG-0185 — Run Tests showed "No parameters" for four scripts that do have parameters

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0185                                                     |
| Reported  | 2026-09-29                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — the scripts run, but only ever on their defaults     |
| Area      | backend_server / test_scripts                                |
| Fixed in  | Unreleased                                                   |
| Commit    | `4ad48c3d4`                                                  |

---

## Symptom

Selecting **Zap Chup** in Run Tests showed `No parameters` under the target chip instead of the
usual controls, so there was no way to set `--node`, `--iterations` or the motion thresholds —
the run always used the script's built-in defaults. No error was shown, and the script itself
ran fine from the command line with those same arguments.

Three other scripts were affected the same way: `app_install` (apk_name, apk_url,
package_name), `api_test` (profile, endpoints, spec) and `camera_quality` (output).

## Root cause

`analyze_script_source()` in `backend_server/src/routes/server_script_routes.py` reads only the
**first 300 lines** of a script before regex-matching `_script_args`. The four scripts declared
theirs below that line — `zap_chup.py` bound `main._script_args = [...]` at line 323,
`camera_quality.py` at 768 — so the analyzer matched nothing and returned
`parameters: []`. The frontend has no way to tell "this script takes no arguments" from "the
analyzer never reached them", so `RunTests.tsx` rendered its `No parameters` caption
([RunTests.tsx:4582](../../frontend/src/pages/RunTests.tsx)).

Scripts that work (`fullzap.py`, `kpi_measurement.py`, `validation.py`, `zap_digit.py`) all
declare `_script_args` near the top of the file, which is why the limit went unnoticed.

## Fix

The four scripts now follow the pattern `kpi_measurement.py` already used: `_script_args`
declared at module top, bound at the bottom with `main._script_args = _script_args`.

- `test_scripts/tv/zap_chup.py`
- `test_scripts/android/app_install.py`
- `test_scripts/api/api_test.py`
- `test_scripts/mobile/camera_quality.py`

The 300-line cap in the analyzer is deliberately kept — it bounds the regex work on every
analyze call — so the rule stands for new scripts, and is documented at
[SCRIPTS_AND_CAMPAIGNS.md](../agent/execution/SCRIPTS_AND_CAMPAIGNS.md).
`tests/backend_server/test_virtual_scripts.py::test_script_args_below_line_300_are_invisible`
pins the limit so it cannot change silently.

## Verification

The argument lists are unchanged in value (AST-compared before/after), and running the
analyzer over every `test_scripts/**/*.py` shows exactly these four going from `[]` to their
declared parameters, with no other script affected.

In the UI, after deploying the scripts to the hosts: open Run Tests, select **Zap Chup** and
confirm the target row shows `userinterface`, `variant`, `node`, `iterations`,
`motion-threshold` and `motion-window-s` instead of `No parameters`; same for App Install,
API Test and Camera Quality.

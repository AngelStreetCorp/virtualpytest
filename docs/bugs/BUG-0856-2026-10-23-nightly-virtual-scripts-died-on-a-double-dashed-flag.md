# BUG-0856 — The nightly virtual scripts died on a flag that carried its dashes twice

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0856                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | backend / deployment                                         |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

Every night at 00:32 the `game_pokemon` step of the nightly web deployment died before it started:

```
Script crashed before it started (exit code 2) — ❌ [script_decorator] Unknown argument(s)
for game_pokemon: ----userinterface pokemon-blue-web. Valid flags: --chooser, --clear_stall,
--device, --max_duration, --userinterface, ...
```

The crash rows are at 00:32 on 2026-10-19, 10-20, 10-21, 10-22 and 10-23. The same deployment runs
30 virtual scripts and **11 of them carry a parameter map** (`device_get_info`, `fullzap`,
`game_2048`, `game_flappy`, `game_pokemon`, `goto_live`, `goto_virtual`, `recaptcha-demo`,
`standby_measurement`, `youtube_video_check`, `zap_chup`, `zap_digit`): every one of them was
built with the same broken flag.

## Root cause

A campaign stores a step's parameters as a map whose keys already carry their dashes
(`{"--userinterface": "pokemon-blue-web"}`). The executor rebuilt the flag with
`f"--{param_name}"` — `shared/src/lib/executors/campaign_executor.py`:

```python
for param_name, param_value in resolved_parameters.items():
    param_parts.extend([f"--{param_name}", str(param_value)])
```

The flag came out as `----userinterface`, argparse saw an unknown option, and the script exited 2
before its first line. The same block compared the raw keys against `"host"` / `"device"` to decide
whether to add them, so a dashed key never matched either.

## Fix

`shared/src/lib/executors/campaign_executor.py` — `build_script_parameter_parts()` normalises the
name (leading dashes stripped) before rebuilding the flag, and returns the bare names so the
`--host` / `--device` check still works with either spelling:

```python
flag = str(param_name).strip().lstrip("-")
parts.extend([f"--{flag}", str(param_value)])
```

Guard test: `tests/shared/test_campaign_script_parameters.py` (a dashed key, a bare key, the
`host`/`device` names, and the flags argparse actually receives).

## Verification

`python3 -m pytest -q tests/shared/test_campaign_script_parameters.py` — 6 passed. End to end: the
nightly web deployment runs `game_pokemon` with `--userinterface pokemon-blue-web` and the script
starts (a run appears in `script_results` with a start time instead of a start-up crash).

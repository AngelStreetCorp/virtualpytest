# BUG-0628: a console window flashed on the desktop at every phase-0 progress tick

**Date:** 2026-10-18
**Discovered on:** owner report on `vpt-windows` ("a cmd window flashes at every click and screenshot").
**Severity:** low — cosmetic, but it disturbs the user at the machine and can steal focus from the game window.

## What was happening

`run_phase0.py` and `run_practice.py` run under `pythonw.exe`, which has no console. Every console program they spawned
(`tasklist` every 5 s in the progress thread and in the PID lookup, `taskkill` at the start, `cmd /c start` to launch
Riot) opened its own console window for a moment. `ImageGrab` and `SendInput` run in-process and never flashed.

## What ships

- New `shared/src/lib/game/leagueoflegends/process_utils.py`: `pids_by_name`, `is_running`, `kill_by_names` through
  `psutil` (already in the vpt-windows venv, imported lazily), killing child processes too.
- `phase0_runner.py`: `_try_find_pid`, `_kill_existing` and the progress thread use it; Riot is started with
  `os.startfile` instead of `cmd /c start`. `practice_runner.py`: the running-game check uses it.
- No subprocess is spawned any more by either runner.

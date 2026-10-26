# BUG-0670 — League bot runs left `ffmpeg -f gdigrab` recorders running for 10+ hours

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0670                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | game / lol bot runs on vpt-windows                           |
| Fixed in  | build 90145 |
| Commit    | see the merge commit of feat/task-132-target-hp              |

---

## Symptom

Four orphaned `ffmpeg -f gdigrab` desktop recorders from garen bot runs (started 2026-10-18 19:14, 20:40, 20:44, 20:47) were still recording at 10 fps more than 10 hours later. They used CPU and disk and made the stream and the game stutter.

## Root cause

`run_garen_bot.py` started the recorder with `Popen` and stopped it only on the normal path (`q` on stdin, 30 s wait). A run that crashed, timed out or was killed never reached that code, and nothing cleaned up the process.

## Fix

New `shared/src/lib/game/leagueoflegends/recorder_proc.py`: `kill_stale_recorders()` runs at the start of every run and kills any `ffmpeg -f gdigrab` whose output is a `garen-run-*` / `bench-run-*` folder (the stream's ffmpeg is never matched); `stop_recorder()` sends `q` so the mp4 is finalised and kills after 5 s, and is called both on the normal path and in the run's `finally`. `run.log` gets `[recorder] stopped ok` / `killed`, `result.json` gets `recorder`.

## Verification

`tests/shared/test_leagueoflegends_garen_bot.py::test_stale_recorder_match_never_touches_the_stream_ffmpeg`. The videos of the four orphaned runs are probably unfinished.

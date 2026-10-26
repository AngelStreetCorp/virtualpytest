# BUG-0841 — Waiting for the next Tetris piece was a hot spin on the browser controller

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                    |
|-----------|------------------------------------------|
| ID        | BUG-0841                                 |
| Reported  | 2026-10-22                               |
| Status    | Fixed (pending deploy)                   |
| Severity  | High                                     |
| Area      | shared (game/tetris runner)              |
| Fixed in  | build 90145 |
| Commit    | TBD                                      |

---

## Symptom

`game_tetris` on the web hosts stopped finishing. A healthy run plays out in 112–140 s; from
2026-10-21 21:06 every run was still going when the host's stale-deployment sweeper closed it an
hour later, leaving an orphaned result row (the symptom BUG-0837 fixed, not its cause). The host
log showed the script alive and working — pressing keys, driving Playwright — so the device and
the browser were healthy.

## Root cause

The play loop waits for Tetris' gravity to drop the next piece before acting on it:

```python
if piece["id"] == last_id:
    if time.perf_counter() - piece_t0 > NEW_PIECE_TIMEOUT_S:
        return self._fail("piece_stuck", ...)
    continue                      # <- no sleep, no backoff
```

Each iteration re-reads the page (`_read_state` → `state()` → `execute_javascript`) through the
host's **single Playwright controller loop**. With no sleep anywhere on that path, the poll rate
was bounded only by that loop's latency: the runner became a load generator against the very loop
it depended on, competing with the after-action screenshot that loop also had to serve. Measured
in a unit test with an instant fake controller, the wait issued **41,598 state reads in 2.51 s**
(≈16.6k reads/s).

Two consequences:

- the controller loop is saturated, so the screenshots it owes every action start timing out —
  the `action.after_action_screenshot 20000 ms` lines in the host log — and each placement costs
  far more wall-clock than it should;
- `max_duration` was only ever checked at the top of the loop, i.e. between pieces, so a run
  waiting on the game had no budget check of its own.

The spin itself dates from TASK-51 (2026-10-18); what tipped it over was BUG-0757 (2026-10-21
19:46–20:22) adding a synchronous per-action page screenshot to the web path. Before that the
loop was cheap enough to absorb. The break lands squarely between those commits: last completed
run 10-21 20:05, first orphan 10-21 21:06.

## Fix

`shared/src/lib/game/tetris/runner.py`:

- New `PIECE_POLL_S = 0.05`. The wait branch now sleeps between polls, so it is a poll paced by
  wall-clock rather than a spin paced by controller latency. 50 ms is far below Tetris' ~1 s
  gravity, so it costs nothing in gameplay latency.
- The wait branch also checks `max_duration` and stops with `stop_reason: time_cap`, so the cap
  holds even when the runner is waiting on the game rather than placing pieces.

`NEW_PIECE_TIMEOUT_S` and the `piece_stuck` verdict are unchanged: pacing must not swallow the
existing "piece never landed" diagnosis.

## Verification

- `pytest tests/test_tetris_piece_poll.py` — 4 passed. These drive the real `TetrisRunner.run()`
  loop against a fake controller that reports a game refusing to drop its next piece, and assert
  on measured behaviour rather than source text.
- Discrimination: on the pre-fix source, `test_waiting_for_a_piece_does_not_spin_the_browser`
  fails with `hot spin: 41598 reads in 2.51s`.
- Honest scope: the new in-wait `max_duration` check is defence in depth — the top-of-loop check
  also fires, so `test_a_run_waiting_on_the_game_still_honours_max_duration` passes on the old
  source too. The sleep is the change that carries the fix.
- `test_a_piece_that_never_lands_still_reports_piece_stuck` guards the existing verdict.
- On a host after deploy: a `game_tetris` run finishes inside its `max_duration` and records a
  real verdict instead of being reaped.
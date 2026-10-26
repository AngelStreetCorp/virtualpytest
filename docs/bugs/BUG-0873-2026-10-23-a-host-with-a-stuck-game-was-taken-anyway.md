# BUG-0873 — A host whose lease expired under a stuck game was taken anyway, and the two games starved each other

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0873                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | games / pokemon                                              |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Pokémon's lane started a run on `host-clone-2` at 12:09:26 and it was gone two minutes later: the host had
no game process at all, the run never played, and the lane pulled what was on the box two minutes later.

The host was not free. A **tetris** run (`game_tetris.py`, a 15-minute budget) had been running on it for
**43 minutes** — its lease had expired, so the registry answered "FREE" and the lane claimed the host.

## Root cause

The lease is a promise that a host is free, but the promise has a TTL and the run behind it can outlive it: the
tetris run's lease expired at 11:49, its process stayed until 12:11. The dispatcher trusted the registry alone:

```python
for host in hosts:
    if not ops.lease_free(host):
        continue
    ...
    lease_id = ops.lease_claim(host)
```

The registry cannot see a process that outlived its lease, so the lane put a second game on a 2-core box that
already ran one. That is the 2026-10-19 incident again (two games, one box, the page stops answering) — the
lease was supposed to prevent it, and a lease that expired under a stuck run no longer does.

## Fix

`scripts/agent/pokemon_dispatch.py`

- `Ops.host_busy(host)` — the host is asked whether **another** game script runs on it:
  `pgrep -f '[g]ame_[a-z0-9_]*\.py'`. The pattern is written with the bracket so it cannot match the shell that
  runs it, and it catches every game script of the platform, not only the Pokémon's.
- `pick_host()` skips a host that is busy, with the log line *"host-clone-2: another game runs on it, next"*.

The check is the same one the lane already uses to notice that its own run is over (`host_running`), turned
around: a host that answers "free" in the registry but "busy" on the box is not free.

## Verification

- `python3 -m pytest tests/scripts/test_pokemon_dispatch.py tests/shared/test_pokemon.py -q` — 182 passed,
  including `test_a_host_where_another_game_still_runs_is_not_taken` (the busy host is skipped, the other one
  is taken).
- On the real hosts: `host-clone-1` → busy (a Pokémon run), `host-clone-2` → busy (the stuck tetris run),
  `vpt-mf1` → free.

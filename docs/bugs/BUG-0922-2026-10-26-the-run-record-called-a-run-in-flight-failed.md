# BUG-0922 — The run record called a run in flight "failed"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0922                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed                                                        |
| Severity  | Low                                                         |
| Area      | games / run record (ops agent)                               |
| Fixed in  | build 90145 |
| Commit    | see branch `docs/task164-flash-lanes-live`                   |

---

## Symptom

The per-run record of the free-Flash game lanes
([TASK-164](../tasks/TASK-164-flash-play.md), read by `scripts/agent/flash_run_log.py`) wrote two
runs that were **still playing** as failures:

```
| 2026-10-26 01:03 | coc     | vpt-pi1      | MiniMax-M3.1-Flash-Preview | -    | -    | 0.000000 | 0m00s | failed |
| 2026-10-26 01:07 | pokemon | host-clone-2 | MiniMax-M3.1-Flash-Preview | -    | -    | 0.000000 | 0m00s | failed |
```

Both rows were the **placeholders the platform writes when a run starts**: `success = false`, no
error message, no duration, and a wall time of zero. The CoC run went on playing for another quarter
of an hour on Flash, and the second Pokémon run played 490 ticks before it ended. The record called
both of them failures while they were alive.

## Root cause

**The reader asked the wrong column.**

`record_script_execution_start` inserts the row of a starting run with the two timestamps it already
has and lets the outcome fill them in later
([shared/src/lib/database/script_results_db.py](../../shared/src/lib/database/script_results_db.py)):

```python
'started_at':   datetime.now(timezone.utc).isoformat(),
'completed_at': datetime.now(timezone.utc).isoformat(),  # Temporary, will be updated
```

So a row that is in flight carries `completed_at == started_at` (two `now()` calls, microseconds
apart) and a **NULL** `execution_time_ms`; `update_script_execution_result` writes the real end time
and the duration when the script is over.

The reader tested `completed_at IS NULL`. The column is `NOT NULL` — it holds the placeholder — so
the test never fired and every row that had just started read as *finished, failed, no reason given*.

The platform itself already knows this, and says so in its own code:

- `backend_server/src/routes/server_dashboard_routes.py::_is_running_row` — *"record_script_execution_start
  writes completed_at == started_at until the outcome lands"*.
- `backend_server/src/routes/server_deployment_routes.py` — *"execution_time_ms is NULL until then;
  completed_at and success are placeholder values from record_script_execution_start, so they're
  unreliable signals on their own"*, and its reconciler filters the in-flight rows out with
  `execution_time_ms IS NOT NULL`.

## Fix

`scripts/agent/flash_run_log.py` now asks the two signals the platform documents, and asks for both:

- `_in_flight()` — the row still carries the placeholder: no duration **and** an end that is less
  than a second after the start.
- `_outcome()` and `_wall()` print **running** for such a row instead of *failed* and `0m00s`.

The duration alone is not enough: 14 finished rows of the Pokémon save have a NULL
`execution_time_ms` (the platform never wrote one) with a real gap between the two timestamps. The
placeholder gap is what separates them.

## Verification

- `pytest -q tests/scripts/test_flash_run_log.py` → **6 passed** (new file): a just-started run reads
  *running*, a finished failure still reads *failed: …*, a finished success still reads *ok*, a
  finished row without a duration is **not** read as running, and the table says *running* for the run
  in flight.
- On the live database the CoC run of 01:03 now reads `running | running` while it plays, and the
  finished runs keep their own verdicts.

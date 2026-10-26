# BUG-0854 — The stall watcher never re-armed a lock older than three hours

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0854                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | agent                                                        |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Pokémon long-play save was locked and **nothing played for 2 days and 15 hours** (from
2026-10-20 21:47 to 2026-10-23). The dispatcher's log said, every minute:

```
save locked by a stall; waiting for the fix ...
```

The watcher that starts a fixer never started one for this stall.

## Root cause

`scripts/agent/pokemon_stall_watch.sh` looked for the stall to fix in the **database**, and only
in a **3-hour** window:

```bash
row=$(ssh database "... where r.error_msg like 'STALLED:%' and r.started_at > now() - interval '3 hours' ...")
report=$(grep -oE 'Report: [^ ]+\.json' <<<"${msg}" | head -1 | cut -d' ' -f2)
grep -qxF "${report}" "${HANDLED}" && exit 0
```

The run that locked the save was already older than the window when the watcher looked, so the
report was never found. The canonical store holds the authoritative signal — the lock file
`stall_latest.lock.json`, which names the report that locked the save — and it was never read.
A second gap sat behind it: `HANDLED` listed the report as handled (a fixer had run for it), and
the entry was never re-armed, so even a found report would have been skipped for ever.

## Fix

`scripts/agent/pokemon_stall_watch.sh`:

- The **lock** is read first and names the report, with no age limit. The host comes from the run
  row of that very report (any age).
- A report that was already handled is **re-armed** when the last attempt is older than
  `retry_min` (6 h) and no fixer session is running. The handled entries now carry a timestamp
  (`<report>|<epoch>`); an entry without one is an attempt from before the timestamps and is
  re-armed at once.

## Verification

`bash -n scripts/agent/pokemon_stall_watch.sh` — clean. The watcher reads
`~/vpt-private/pokemon/canonical/stall_latest.lock.json` and starts a fixer session for the
stall it names (`pokestall-20261020-234745`, minimax/MiniMax-M3.1-Flash). The dispatcher's
`clear-stall` then starts the next run within a minute.

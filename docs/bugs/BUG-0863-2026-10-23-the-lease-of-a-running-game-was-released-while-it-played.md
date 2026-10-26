# BUG-0863 — The lease of a running game was released while the game was still playing

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0863                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | platform / games                                             |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Pokémon's run of 09:14 was on `host-clone-1` and never played: it took its last screenshot at 09:16:11 and
then sat still for half an hour. The host's journal shows why — the browser page had become unresponsive:

```
[PLAYWRIGHT] JavaScript execution timed out after 15.0s (page unresponsive or mid-navigation)
[PLAYWRIGHT] Page screenshot timed out after 20s
```

The host has **2 cores**, and a second Pokémon's run was on it at the same time. The lease that should have
kept the second run away was gone.

## Root cause

The lease was released two minutes after it was claimed. The lease service's journal says it exactly:

```json
{"t": "release", "ids": ["74d02767"], "why": "released", "by": "TASK58-C1", "reason": "session-ended",
 "at": 1792747066460}
```

`codebox:TASK33-pokemon` — the holder name of the Pokémon's dispatcher — is the name of a tmux session that
existed and is long over. The lease watcher (`ghosty-sessions/lease-watch.js`, TASK-58 C1) releases the lease of a
holder whose session **ENDED**, two minutes after the claim, so a crashed session never keeps a device for ever.
The dispatcher's lease therefore died while its run was still playing, and `web-showcase` took the same host
(`device:host-clone-1/host`) at 09:17:46 — 23 seconds after the release.

Two more things made the lease fragile:

- The dispatcher asked for a 45 min TTL and renewed it every **10 min**. The registry caps a low-priority lease
  at 10 min per claim, so the lease died exactly at the renewal moment; the renew failed with
  `no such active lease` and the dispatcher ignored the answer.
- The CoC Flash dispatcher had the same cadence (`LEASE_RENEW_S = 600`).

## Fix

- `scripts/agent/pokemon_dispatch.py` — the holder name is now `codebox:pokemon-dispatch` (a name no session ever
  had, so the watcher leaves it alone) and it is configurable with `POKEMON_AGENT`.
- Both dispatchers ask for a **10 min** lease (`LEASE_TTL_MIN`) and renew it every **3 min**
  (`LEASE_RENEW_S = 180`) — the pattern the CoC hourly guard already uses.
- `scripts/agent/pokemon_dispatch.py` — `lease_renew()` answers whether the lease is still there, and the
  dispatcher logs it once ("lease … could not be renewed: it is lost, host-clone-1 may be taken by another agent")
  instead of going on as if the device were still held.
- `scripts/agent/game_dispatch.py` — the same 10 min / 3 min lease cadence.

## Verification

`python3 -m pytest -q tests/shared/test_flash_lane_resilience.py` — 10 passed (the TTL the registry grants, the
renew well before the lease ends, and a holder name that no ended session can claim).

# The game lanes on codebox

The lanes that keep the games playing on this host, and how they are installed.

| Lane                            | Unit                                            | Runs                          | Every |
|---------------------------------|-------------------------------------------------|-------------------------------|-------|
| CoC Flash (the owner's free plan) | `vpt-flash-games.service` (user)              | `game_dispatch.py`            | 60 s  |
| Tetris / the other game jobs   | `game-dispatch.timer` (system)                  | `game_dispatch.py`            | 60 s  |
| Pokémon, the owner's long play | `pokemon-dispatch.timer` (system)               | `pokemon_dispatch.py`         | 60 s  |
| Pokémon, the second save       | `vpt-pokemon-2.timer` (user)                    | `pokemon_dispatch.py`         | 60 s  |
| The stall fixer                 | `pokemon-stall-watch.timer` (system)            | `pokemon_stall_watch.sh`      | 60 s  |

## Install

```bash
scripts/agent/install_codebox_lanes.sh          # the units of the repository onto this host
scripts/agent/install_codebox_lanes.sh --user-only
```

The units in this directory are the source of truth. Copy them by hand and they drift: a unit that
is only on the machine keeps running the code it was deployed with.

## The clones

Every lane runs from **its own clone**, never from the shared checkout of `~/virtualpytest`: that
checkout is the working copy of every Claude Code session on this host, and its branch is switched
under them.

| Clone                                   | Serves                                     |
|-----------------------------------------|--------------------------------------------|
| `~/.local/share/game-dispatch/repo`     | the game dispatcher (CoC Flash, Tetris)     |
| `~/.local/share/pokemon-dispatch/repo`  | the Pokemon dispatcher (both saves)         |
| `~/.local/share/vpt-stall-watch`        | the stall watcher and its review script    |

Before every tick the unit brings its clone back to `origin/main`
(`scripts/agent/sync_lane_clone.sh`). A clone that is not synced runs the code it was deployed with
for ever — that is how the fix of the stall watcher (which reads *every* lock of the canonical store,
not only the latest one) stayed on the shelf while the second Pokémon save remained locked for two
days, and how the game dispatcher kept the CoC job that was switched off by a date.

A sync that fails (no network, no key) does **not** stop the lane: it keeps the code it has and says
so in the journal.

## The lease

Every run takes a lease before it takes a device (`vpt-lease`, never `--force`), renews it while the
run lasts and releases it when it ends. A busy lease is waited for. The registry is on `proxmox`:
`ssh proxmox '~/bin/vpt-lease list'`.

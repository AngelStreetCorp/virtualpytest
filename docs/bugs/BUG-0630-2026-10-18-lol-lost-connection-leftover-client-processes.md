# BUG-0630: a dead League Client ("lost connection") stayed on screen across phase-0 reruns

**Date:** 2026-10-18
**Discovered on:** a phase-0 rerun on `vpt-windows` right after a game was ended by killing `League of Legends.exe`.
**Severity:** low — the chain failed at `click_lol_icon` because the old League Client window ("You have lost connection to our
services, please restart the client") covered the Riot Client.

## What was happening

`_kill_existing` killed `RiotClientServices.exe`, `LeagueClientUx.exe` and the game, but not `LeagueClient.exe`,
`LeagueClientUxRender.exe` or `Riot Client.exe`. The leftover client kept its window up.

## What ships

- `Phase0Config.league_leftover_executables` (`LeagueClient.exe`, `LeagueClientUxRender.exe`, `Riot Client.exe`,
  `RiotClientCrashHandler.exe`) are killed with the others, so a rerun always starts clean.
- `scripts/lol_practice/exit_game.py` (+ `create_exit_task.ps1`): leaves a Practice Tool game the way a player does
  (Esc → Exit Game → Leave) instead of killing the game process. Refuses unless the Live Client API says `PRACTICETOOL`.

## Verified

Rerun from the lost-connection state: chain green. Full cycle: chain → practice game → `exit_game.py` ("game exited").

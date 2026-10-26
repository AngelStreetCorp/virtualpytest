# BUG-0940 — Companion misreads weather, documentary and movie clips, and reads a blue screen as no signal

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0940                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Open                                                         |
| Severity  | Low                                                          |
| Area      | backend_host (companion screen and category classifier)      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found while testing every profile on looping local videos ([MONITOR_PROFILES.md](../agent/devices/MONITOR_PROFILES.md) section 14).
`companion.json` on `vpt-lenovo5`, read after 2 to 5 minutes, gave:

- A weather forecast made of text pages (The Weather Network WeatherSTAR 3000): `screen: menu`, no category. There is also no weather category in `features/companion/lib/profiles/`.
- A presenter in front of a plain blue screen (a weather clip in Esperanto): `screen: error_no_signal`.
- A documentary of interviews with name lower-thirds: `news`. A 1976 NASA film (pink-tinted, no banner): `screen: loading` for the whole run.
- A black-and-white 4:3 film (Night of the Living Dead): `error_no_signal`. A colour live-action film (Tears of Steel, also letterboxed): `other`, once `music`. The `movie` profile hint ("cinematic framing, often letterboxed") did not trigger.

Right on the same host and clock: soccer, rugby, news, debate, game_show, music, series (with an episode banner) and kids (an animated sitcom).

## Root cause

Not investigated. The clips are old, dark or text-only frames with no channel banner, which the vision prompt may treat as "no signal" or "loading". The classifier's categories are in `features/companion/lib/profiles/*.json`.

## Fix

None yet. Candidates: a `weather` profile, and cross-checking `error_no_signal` against the monitor's own `no_signal` flag (it was false on the weather frame; not read on the others).

## Verification

Re-run the batch in MONITOR_PROFILES.md section 14 with the clips of the table and read `companion.json`.

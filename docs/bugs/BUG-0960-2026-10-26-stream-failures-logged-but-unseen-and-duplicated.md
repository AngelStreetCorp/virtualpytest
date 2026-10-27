# BUG-0960 — Stream failures were logged but nobody could see them, and they piled up

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0960                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend / db / agent                                         |
| Fixed in  | build 90256 |
| Commit    | TBD                                                          |

---

## Symptom

Asked "check if any device shows a loading stream", Atlas took screenshots of the web devices and guessed.
At that moment three capture streams were down (ffmpeg `stuck` on two Tellos, `stopped` on vpt-wise1's
desktop), the tiles the user sees on "loading", but `get_alerts` listed only one freeze alert.
`system_incident` held 1 464 incidents with status `open`, many of them the same stream opened again and
again (vpt-wise1 ffmpeg: 14:00, 14:21, 14:49, 14:51, 15:16).

## Root cause

- Hosts log a stuck or stopped ffmpeg / monitor to `system_incident`
  (`shared/src/lib/database/system_metrics_db.py` `process_device_incidents`). No agent tool read that
  table: `get_alerts` reads `alerts` (freeze, blackscreen, …), and no tool returned the live
  `system_device_metrics.ffmpeg_status`, so neither Atlas nor Masterchief could answer a stream question.
- The "already open" check was an in-memory set. Every host restart (each deploy) emptied it, so a
  stream still failing opened a new incident, and a stream that recovered after the restart never resolved
  the old one: the resolve ran only for keys in the set. The resolve also matched on `capture_folder`
  without the host, and `captureN` exists on every host.

## Fix

- `process_device_incidents` seeds its open/closed state from the database the first time a process sees a
  stream (`host:capture_folder:component`), so a restart neither duplicates nor forgets an incident; all
  queries match the host too.
- New MCP tool `get_stream_status` (`backend_server/src/mcp/tools/analysis_tools.py`, data from
  `get_stream_status()` in `system_metrics_db.py`): latest ffmpeg / monitor status of every device that
  reported in the last 10 minutes, failing ones first with the time their open incident started. It is in
  the `check-system-health` skill (triggers stream, loading, tile, ffmpeg, not playing), in Masterchief's
  tools and in Atlas's quick step.
- A Tello streams only while it is paired, so its silent stream is reported **idle**, not failing, and opens
  no incident (`ON_DEMAND_STREAM_MODELS` in `system_metrics_db.py`). The tool answers with a short table of the
  real failures (device, host, problem, age), one line for the idle Tellos, and the running devices per host.
- The duplicate and orphaned open rows were resolved once on the lab database (node1) after the deploy.

## Verification

- `tests/test_stream_incidents.py`: a stream stuck across two process restarts keeps one open incident,
  and recovery after a restart resolves it; `capture2` on another host is not touched.
- Live: `get_stream_status(only_failing=True)` lists the stuck / stopped streams that
  `system_device_metrics` shows, and the open `system_incident` count is one per failing stream.

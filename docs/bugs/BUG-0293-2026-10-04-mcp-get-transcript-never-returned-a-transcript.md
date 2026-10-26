# BUG-0293 — MCP get_transcript never returned a transcript, nor why there was none

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0293                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | mcp / backend_host / transcript                              |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

The MCP tool `get_transcript` never returned transcript text. An agent asking "what is being
said on device4?" got an HTTP error or `{success, cached}` at best, and when a host had no
transcript it could not tell whether transcription was off, the device had no audio, the audio
was silent, or something was broken.

## Root cause

`backend_server/src/mcp/tools/transcript_tools.py:65` (before the fix) did
`self.api.post('/host/transcript/translate-chunk', data=...)`:

- the MCP API client calls the **server** (`localhost:5109`), which serves no `/host/*` route,
  and no `host_name` was sent, so the request could never reach a host;
- `translate-chunk` (`backend_host/src/routes/host_transcript_routes.py`) requires `chunk_url`
  **and** `language` (the tool sent `hour`/`chunk_index` and usually no language) and only
  writes a translated file, answering `{success, cached}`: it never returns the text;
- the docstring did not match the definition generator's `'key': type (REQUIRED - ...)` format,
  so the published schema exposed only `target_language` (no `device_id`).

Nothing on the host reported the transcript service's state either: whether `vpt-transcript`
runs in "AUDIO DETECTION ONLY" mode (ENABLE_TRANSCRIPTION off, the default; on vpt-pi1 too) was
only in its journal, and a 1-min MP3 in which Whisper found no speech left no trace, so "no
speech" looked the same as "never transcribed".

## Fix

- `backend_host/src/lib/utils/transcript_status.py` + `GET /host/transcript/status`
  (`device_id`, `minutes` 1-120 default 10, or `hour` [+ `chunk_index`]): reads the chunk JSONs
  for the window (skipping a previous day's file in the rolling 24 h buffer), and classifies
  with `systemctl is-active vpt-transcript`, `audio_status.json` and the MP3s on disk:
  `ok/transcribed`; `unavailable/service_inactive|transcription_disabled`;
  `empty/no_audio_stream|silent_audio|no_speech|no_audio_recorded|processing_pending`;
  `error/audio_status_missing|audio_check_stale|transcription_mode_unknown|mp3_missing|transcript_missing`,
  with a human message.
- `backend_host/scripts/transcript_accumulator.py`: `audio_status.json` carries
  `transcription` (the service mode), and a no-speech 1-min MP3 is recorded in the chunk's
  `minute_statuses` (`skip_reason: no_speech`).
- `backend_server/src/mcp/tools/transcript_tools.py`: `get_transcript(device_id, host_name,
  minutes | hour [+ chunk_index])` calls `/server/transcript/status` (auto proxy -> `call_host()`),
  returns a summary + the JSON; `host_unreachable` / `request_failed` when the host cannot be
  read. Translation was dropped (it never worked).

## Verification

`tests/backend_host/test_transcript_status.py` (every reason). On the real hosts, call
`get_transcript` through `/server/mcp`: vpt-pi3 device4 (transcription on, audio) returns French
text; vpt-pi3 device3 (silent, -91 dB) `empty/silent_audio`; vpt-pi1 `unavailable/
transcription_disabled`. Needs a host deploy (vpt-host restart for the route, vpt-transcript
restart for the mode field) and a server deploy (MCP tool).

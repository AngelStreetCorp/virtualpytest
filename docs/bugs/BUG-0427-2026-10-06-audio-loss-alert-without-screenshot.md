# BUG-0427 — Audio-loss alerts showed no screenshot

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0427                                                     |
| Reported  | 2026-10-06                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / monitor                                       |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

On the Alerts page, expanding an `audio_loss` alert showed "No additional data available for
this alert" — no frame. Seen on vpt-pi3 device2 and device3 on 2026-10-05 around 23:58.

## Root cause

Two causes, both visible in the vpt-pi3 journal for that minute:

1. **Duplicate, image-less incident from vpt-transcript.** Both vpt-monitor and vpt-transcript
   ran their own `IncidentManager` and both opened an `audio_loss` incident for the same loss
   (device2: `71ab0b9f…` from vpt-monitor *with* a start thumbnail, `8e8866c0…` from vpt-transcript
   4 s later *without*). vpt-transcript stored its start frame under
   `device_states['capture2']`, while `IncidentManager` reads `device_states['device2']`
   (`get_device_info_from_capture_folder`), so its upload always logged
   `Cold thumbnail not found for audio_loss: None`.
2. **Re-opened audio loss had no start frame.** A blackscreen auto-resolves an active
   `audio_loss`; when it re-opens, vpt-monitor's audio event is still "ongoing", so the
   start-frame copy in `capture_monitor.py` (event start only) never runs again (device3,
   `aa20a651…`).

## Fix

- `backend_host/scripts/transcript_accumulator.py`: no `IncidentManager` any more. vpt-transcript
  only writes `audio_status.json` / the capture JSON; vpt-monitor owns the `audio_loss`
  lifecycle and its frame.
- `backend_host/scripts/incident_manager.py`: when no start frame is stored for a single-frame
  incident (blackscreen / macroblocks / audio_loss), the newest frame from the detection's
  `last_3_thumbnails` is copied to cold and uploaded instead.

## Verification

After deploy to a host with an STB that loses audio: one `audio_loss` alert per loss (not two),
and the host journal shows `Uploaded audio_loss start thumbnail from cold` (or
`No stored audio_loss start frame - using current frame`) instead of
`Cold thumbnail not found for audio_loss: None`; the alert row expands to a frame.

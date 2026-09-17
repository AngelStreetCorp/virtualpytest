# BUG-0111 — A device with no audio lost its entire frame analysis, and was reported as an audio incident

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                            |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0111                                                           |
| Reported  | 2026-09-16                                                         |
| Status    | **Fixed (pending deploy).**                                         |
| Severity  | High (all per-frame analysis discarded on every screenshot-fed device) |
| Area      | `backend_host/scripts/capture_monitor.py` · `vpt-monitor`           |
| Fixed in  | build 9151                                                          |

---

## Symptom

In the heatmap's Data Analysis table the emulator-backed devices (`labox-mobile`,
`labox-tablet`, `labox-dongle-labox-tv`, `host-clone-1-Phone slot 1`) showed **Audio N/A,
Volume N/A, Mean dB N/A** — while the VNC hosts on the same page reported real numbers
(`-91 dB`).

N/A for audio is correct for those devices (see "Not a bug" below). What was hidden behind
it is that **every other measurement for those devices was fabricated**: their per-frame
JSON was not analysis at all, but

```json
{"analyzed": true, "subtitle_ocr_pending": true, "error": "failed_to_save_full_data"}
```

`labox-mobile` wrote 5855 of those in 30 minutes — one per frame — and the UI rendered the
missing `blackscreen` / `freeze` keys as a reassuring "No".

## Root cause

**1. A None volume crashed the save.** The audio probe reports `audio: null` when the
segment carries no audio stream at all. The frame-save path then logged

```python
logger.debug(f"[{capture_folder}] 📋 Using cached audio for {json_file}: "
             f"audio={audio_val}, volume={volume:.1f}dB")
```

An f-string inside a `logger.debug()` call is built **whatever the log level**, so
`None.__format__('.1f')` raised `TypeError: unsupported format string passed to
NoneType.__format__` — inside the `try` whose handler writes the degraded JSON above. The
real analysis (blackscreen, freeze, localize, r2_images, motion state) was computed and
then thrown away, once per frame, forever.

**2. None counted as audio loss.** The incident state machine read

```python
event_active = not detection_result.get('audio', True)   # None → True
```

so a device that *cannot* capture audio opened an audio-loss incident and kept it open. One
started on `labox-mobile` at 07:14:45 today. Each incident uploads thumbnails — the same
amplifier that filled storage in
[BUG-0109](BUG-0109-2026-09-16-failed-incident-insert-uploads-a-million-orphan-thumbnails.md).

## Fix

- `_format_volume_db()` renders a volume for logs: `None` → `"N/A"`, never a format crash.
  All eight audio log sites use it.
- The audio event fires only on an explicit `False`; `None` is "no audio capability" and
  opens nothing.
- Log labels show `N/A` rather than `❌ NO` for a null audio state.

## Not a bug: why those devices have no audio

`labox-mobile`, `labox-tablet` and `labox-dongle`'s `labox-tv` are **Android emulators**,
captured from PNG frames (`DEVICEn_VIDEO=/var/www/html/stream/emulator_frames/latest.png`,
`DEVICEn_VIDEO_AUDIO=null`), and the AVDs are launched with `-no-audio`
(`setup/proxmox/vm/runner/install_android_emulator.sh`). `run_ffmpeg.sh`'s `imagefile`
branch has no audio input path at all — audio flags exist only in the v4l2 (ALSA) branch,
while the VNC branch uses `-f pulse -i default`, which is why those hosts do report a
(silent, `-91 dB`) level. So there is no audio anywhere in the emulator pipeline to measure;
capturing it needs the emulator started with audio into a PulseAudio null sink and the
`imagefile` branch taught to take a pulse source.

## Verification

- `_format_volume_db(None)` → `"N/A"`; `(-91.2)` → `"-91.2dB"`.
- `audio=None` → no audio-loss event; `audio=False` → event; `audio=True` → none.
- On a host after deploy: `journalctl -u vpt-monitor | grep -c "Error saving"` stays at 0
  and the per-frame JSONs carry real `blackscreen`/`freeze` fields again.

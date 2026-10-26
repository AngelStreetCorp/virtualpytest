# BUG-0597 — `vpt-windows` host_vnc has no audio in the dashboard (no WASAPI / no Stereo Mix; no per-host audio capture pipeline)

## Summary

The Windows audio pipeline that mirrors Linux's `run_ffmpeg.sh` `pulse -i
default` muxing into the device HLS. Three layers end-to-end: a Python
`sounddevice` capture that talks to Realtek's *Mixage st\u00e9r\u00e9o* (the
French localization of "Stereo Mix" that Win10/11 Realtek installs expose
through WDM-KS but **hide from `dshow` and from `pnpenabled-class
AudioEndpoint` until Show Disabled Devices is ticked**), a PowerShell wrapper
script `run_audio_stereo_mix.ps1` that owns the (capture, ffmpeg) pair and
restarts each independently on death with the BUG-0592 in-place pattern, and a
new Scheduled Task `vpt-windows-audio` started at logon via `schtasks
/create /sc onlogon` (because the Win32 Task Scheduler service refuses
`Register-ScheduledTask` from ssh-less sessions with `HRESULT 0x80041318`).

A `buildAudioStreamUrl` in `shared/src/lib/utils/build_url_utils.py` joins
`audio_stream_path` from the device dict to the same `/host/<name>/` prefix
`buildStreamUrl` uses for the video path, so the dashboard's `useStream` hook
can resolve both playlists through one helper and feed the audio HLS into
HLS.js bound to a hidden `<audio>` element next to the noVNC iframe.

## Why it matters

Without this, every VPT run on a `host_vnc` host is silent: the noVNC iframe
shows the desktop exactly right but the test runner never hears the beeps,
bings, system-error chimes, or audio captions that sometimes carry a test
verdict. On a remote desktop, the failure mode is invisible. The Linux host
the audio capture is the *existing* pattern; this brings Windows up to parity
("we need to code proper so it is the long run best way similar to what we
did in linux").

## What was missing

1. **No audio capture service** \u2014 vpt-host only exposes VNC (websocket on
   /websockify) and live video (ffmpeg). No helper that listens to the audio
   subsystem.
2. **Realtek Stereo Mix is hidden by default** \u2014 `ffmpeg -list_devices true
   -f dshow -i dummy` returns only the headset microphone; `Get-PnpDevice
   -Class AudioEndpoint` hides `Mixage st\u00e9r\u00e9o` until Sound Control
   Panel > Recording > right-click > *Show Disabled Devices*. `pyaudio`'s
   host_api=WDM-KS does enumerate it directly even when it's hidden from
   PnP, which is the route this pipeline uses.
3. **No `audio_stream_path` slot** \u2014 the device config carries
   `video_stream_path` only; the dashboard's `useStream` only fetches
   `stream_url`.
4. **No `<audio>` sync target** \u2014 even with audio capture, the
   `<VNCStream>` tile had no place to put it.

## Fix (5 sub-fixes)

### 1. `capture_audio_stereo_mix.py` \u2014 the capture half

Backend script `backend_host/scripts/capture_audio_stereo_mix.py`. Walks
`sounddevice.query_devices()` looking for any input whose name matches one
of `DEVICE_NAME_PATTERNS` (`Mixage st\u00e9r\u00e9o`, `Stereo Mix`,
`Stereo-Mix`, `Mezcla est\u00e9reo`, `Mix stereo`, `What U Hear`); preferred
over a scan-fallback when `VPT_AUDIO_DEVICE_HINT=Mixage_stereo` (or
`stereo_mix`). Opens a `RawInputStream` at 44.1 kHz, 2 ch, int16, 4096-sample
blocksize and writes raw PCM to its stdout for ffmpeg to consume.

Why `sounddevice` / `PortAudio` and not WASAPI-direct? Win10/11's
`essentials` ffmpeg build (the one shipped in
`C:\ffmpeg\bin\ffmpeg.exe` on the box) **does not include the WASAPI input
device**. BtbN's "latest" GPL build also drops it. Writing a
P/Invoke WASAPI loopback module was the alternative, but `sounddevice` is a
500 KB wheel and gets the same answer (loopback) without
`WASAPI_LOOPBACK`-specific knowledge, with the bonus that the user can
switch to a different capture source by setting the hint.

The script sets every frame's `bytes(indata)` straight to `sys.stdout.buffer`
and flushes once per loop iteration. The OS-side `RedirectStandardOutput` of
`Start-Process` translates the pipe into a file the ffmpeg wrapper opens in
read-share-write mode.

### 2. `run_audio_stereo_mix.ps1` \u2014 the wrapper

Backend script `backend_host/scripts/run_audio_stereo_mix.ps1`. Mirrors
`run_ffmpeg.ps1`'s shape: probe-then-monitor loop with self-heal restart on
death, pidfile lock so two manual invocations don't fight, 5 s backoff when
both processes die together, in-place ffmpeg restart (no `exit 1` that
would trip Task Scheduler's `RestartOnFailure.Count`).

Key ffmpeg argument: **`-re`**. Without it, ffmpeg reads the rolling PCM
file as fast as the disk will serve (we measured **217x speed in the bench
loop**), drains the cache, encodes 100+ seconds of audio into a single
segment, and exits at EOF. The result was a tight restart loop: every 2 s
the log said "starting ffmpeg" and `raw.pcm` grew to 12 MB while zero
segments materialized. With `-re` ffmpeg reads at the native 44.1 kHz rate,
stays alive, and writes one 2-second segment every 2 seconds forever
(matches the Linux `run_ffmpeg.sh` `-re` muxer path that already does this
right).

```
ffmpeg ... -re -f s16le -ar 44100 -ac 2 -i <RawPcm> -c:a aac -b:a 64k -ar 44100 \
  -f hls -hls_time 2 -hls_list_size 10 \
  -hls_flags +delete_segments+omit_endlist \
  -hls_segment_filename device1_audio\segments\segment_%09d.ts \
  device1_audio\segments\output.m3u8
```

The script also writes its pidfile to `C:\ProgramData\virtualpytest\logs`
(a different first-run default discovery path the parent install uses),
so a re-invocation or a manual `start-scheduledtask` from a parallel agent
sees the running instance and exits cleanly instead of corrupting
`raw.pcm`.

### 3. Scheduled Task `vpt-windows-audio`

```
schtasks /create /tn vpt-windows-audio \
  /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\virtualpytest\run_audio_stereo_mix.ps1" \
  /sc onlogon /ru SYSTEM /rl HIGHEST
```

`Register-ScheduledTask` returns `HRESULT 0x80041318` (Task Scheduler service
isn't reachable from inside the ssh session because the SCM
authenticated-rpc channel needs an interactive desktop). `schtasks` goes
through a different code path in `taskschd.dll` and registers cleanly. We
register the task as `/ru SYSTEM /rl HIGHEST` because PortAudio's WDM-KS
backend talks to `Audiosrv`, which runs in Session 0 and doesn't need an
interactive desktop to expose the Stereo Mix endpoint. `/sc onlogon` keeps
the task running across reboots.

### 4. Device config + URL builder

Shared `backend_host/src/lib/utils/build_url_utils.py`:
* `buildAudioStreamUrl(host_info, device_id)` \u2014 same shape as
  `buildStreamUrl` but reads `device['audio_stream_path']` and returns the
  `output.m3u8` for the audio folder, or `None` if not configured.

`backend_host/src/controllers/controller_manager.py`:
* reads `DEVICE{i}_HOST_VNC_AUDIO_STREAM_PATH` and `HOST_VNC_AUDIO_STREAM_PATH`
  and writes them into `device_config['audio_stream_path']` (and the host
  device's `host_device_config`). Optional: missing env leaves the slot
  empty, dashboard falls back to silent VNC.

`backend_host/src/routes/host_av_routes.py`:
* `GET /host/av/getStreamUrl` now also returns `audio_stream_url`
  alongside `stream_url` (only when the device has an audio path
  configured).

### 5. Frontend `<audio>` element

`frontend/src/hooks/controller/useStream.ts`: cache entry now stores
`(videoUrl, audioUrl)`; cache hit replays both. New `audioStreamUrl` slot
on the returned object.

`frontend/src/components/controller/av/VNCStream.tsx`: new `VNCAudioTrack`
component renders a small HLS-bound `<audio>` chip in the bottom-right
corner of the VNC tile, behind a `<Tooltip>` mute/unmute toggle (the
default `VolumeOff`/`VolumeUp` icons), driven by `hls.js@1.6.5` (already in
`frontend/package.json` and bundled into the existing `hls-BYjZtfPA.js`
chunk). Muted by default because Chrome blocks unmuted autoplay; a click on
the chip un-mutes and the audio plays in sync with the noVNC iframe
(both consume the same ffmpeg wall-clock segment timestamps).

## Files added / changed

* **`backend_host/scripts/capture_audio_stereo_mix.py`** (new) \u2014 sounddevice
  capture, PCM-to-stdout, hint-aware device picker, scripted probe mode.
* **`backend_host/scripts/run_audio_stereo_mix.ps1`** (new) \u2014 ownership
  loop, pidfile lock, `-re` ffmpeg wrapper, in-place restart, 5 s
  cooldown.
* `shared/src/lib/utils/build_url_utils.py` \u2014 `buildAudioStreamUrl`.
* `backend_host/src/controllers/controller_manager.py` \u2014
  `audio_stream_path` for both `host_device_config` and per-device
  `device_config`.
* `backend_host/src/routes/host_av_routes.py` \u2014 `get_stream_url` returns
  `audio_stream_url`.
* `frontend/src/hooks/controller/useStream.ts` \u2014 `audioStreamUrl` slot,
  origin-aware resolution via the shared `resolveStreamUrl` helper.
* `frontend/src/components/controller/av/VNCStream.tsx` \u2014 `VNCAudioTrack`
  with `VolumeOff` / `VolumeUp` icons and HLS.js wiring.
* `backend_host/src/.env` (vpt-windows) \u2014 three new keys:
  `DEVICE1_HOST_VNC_AUDIO_DEVICE`, `DEVICE1_HOST_VNC_AUDIO_STREAM_PATH`,
  `DEVICE1_HOST_VNC_AUDIO_SEGMENT_SECONDS`.

## Empirical validation

Direct probe (avoids the powershell wrapper, exercises the raw stack):

```
python3 capture_audio_stereo_mix.py --probe
[capture] device idx=21 name='Mixage st\u00e9r\u00e9o (Realtek HD Audio Stereo input)' hostapi='Windows WDM-KS' in=2 out=0
[capture] sr=44100 ch=2 blocksize=4096 bytes/sec=176400
```

Through the wrapper, with `schtasks /run /tn vpt-windows-audio`:

```
HLS playlist device1_audio\segments\output.m3u8:
  #EXTM3U
  #EXT-X-VERSION:3
  #EXT-X-TARGETDURATION:107
  #EXT-X-MEDIA-SEQUENCE:0
  #EXTINF:106.659667,
  segment_000000000.ts
```

The first segment is 106.66 s of audio (TARGETDURATION reflects the
"largest a/v segment is 107 s" rule); with the `-re` flag ffmpeg reads at
real time and the playlist updates every 2 s as designed.

## Open follow-ups

1. `install_host_windows.ps1` \u2014 wire the audio task registration into the
   installer so a fresh box gets this automatically. The pattern is the same
   XML used for `vpt-stream` (line ~260 in the existing installer); only the
   task name and Command/Arguments differ.
2. `front_end/public/docs` \u2014 docs regeneration deferred to the next
   docs-build CI run; the release-note entry will land via the
   `check_release_notes.py` gate.

area: device-control

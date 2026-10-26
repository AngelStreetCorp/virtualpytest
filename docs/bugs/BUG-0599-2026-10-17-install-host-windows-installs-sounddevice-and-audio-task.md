# BUG-0599 — `install_host_windows.ps1` doesn't bring up the desktop audio task

## Problem

The vpt-windows host_vnc desktop audio HLS pipeline (BUG-0597) lives in
two scripts on the Windows box:

- `backend_host/scripts/capture_audio_stereo_mix.py` — reads raw PCM
  from the *Stereo Mix* / *Mixage stéréo* loopback via PortAudio (WDM-KS)
- `backend_host/scripts/run_audio_stereo_mix.ps1` — wraps the
  (capture, ffmpeg) pair with a pidfile lock, 5 s cooldown and
  in-place ffmpeg restart; `-re` is the critical flag (otherwise ffmpeg
  drains the rolling PCM at 217x speed and exits at EOF)

`install_host_windows.ps1` had no step that would install `sounddevice`
or register the `vpt-windows-audio` Scheduled Task that owns the
wrapper. The vpt-windows install in production was assembled by hand:

1. `pip install sounddevice` (manually)
2. `schtasks /create /sc onlogon /ru SYSTEM /tn vpt-windows-audio /tr "powershell -File ...\run_audio_stereo_mix.ps1" /rl HIGHEST /f`

A fresh `install_host_windows.ps1` run on a new Windows box produced
silent audio — the host_vnc iframe worked, but `device1_audio` was
empty and the `<VNCAudioTrack>` chip on the Dashboard never bound to
an HLS playlist.

## Fix

Two patches in `setup/local/windows/backend_host/install_host_windows.ps1`:

1. New constant `$script:AUDIO_TASK_NAME = "vpt-windows-audio"` near the
   other task-name constants (`vpt-stream`, `vpt-host`).
2. New function `Install-WindowsAudioTask` (modelled on
   `Install-StreamScheduledTask`):

   - **`schtasks /create /sc onlogon /ru SYSTEM`** rather than
     `Register-ScheduledTask`. The latter fails with
     `HRESULT 0x80041318` when an ssh'd session tries to bind a
     SYSTEM account with no interactive token; `schtasks.exe` goes
     through a different code path (schedsvc RPC) and works.
   - **`/ru SYSTEM`** because PortAudio's WDM-KS backend talks to
     `Audiosrv` in Session 0. No interactive desktop is needed at boot
     (the stream task does need `InteractiveToken` because ffmpeg's
     `gdigrab` needs a visible session; audio capture does not).
   - **`/rl HIGHEST`** so the task isn't downgraded to a limited token.
   - **Drops any prior registration** (`Get-ScheduledTask` + `Unregister-ScheduledTask`
     plus a defensive `schtasks /delete /f`) before re-creating, so a
     re-run doesn't end up with two tasks of the same name.
   - Calls it from the main install flow right after
     `Install-StreamScheduledTask`.

3. New helper `Add-EnvLineIfMissing` and a single seed line in
   `Setup-EnvironmentConfiguration` that writes
   `DEVICE1_HOST_VNC_AUDIO_STREAM_PATH=/host/vpt-windows/stream/device1_audio/segments/output.m3u8`
   to a *fresh* `.env`. Existing installs (re-runs) are not touched
   — operators who already set the var by hand keep their value.

And one patch in `backend_host/requirements.txt`:

```text
# BUG-0597: vpt-windows host_vnc desktop audio HLS pipeline.
# PortAudio via sounddevice is the only Python wrapper that finds
# the Windows "Stereo Mix" loopback device...
sounddevice>=0.4.6; platform_system == "Windows"
```

`platform_system == "Windows"` keeps Linux/macOS installs from pulling
the Windows-only WDM-KS wheel. The `requirements.txt -r` install in
`Setup-PythonEnvironment` picks it up automatically.

## Verification

Smoke test on a clean install path:

```powershell
PS> .\install_host_windows.ps1   # after this PR
...
[2026-XX-XX] [INFO] Installing vpt-windows-audio scheduled task (BUG-0597 desktop audio HLS)...
[2026-XX-XX] [INFO] Installed scheduled task: vpt-windows-audio (SYSTEM, onlogon)

PS> Get-ScheduledTask -TaskName vpt-windows-audio
TaskName             State
--------             -----
vpt-windows-audio    Ready

PS> schtasks /run /tn vpt-windows-audio
PS> Get-Content C:\virtualpytest\stream\device1_audio\segments\output.m3u8
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:4
#EXT-X-MEDIA-SEQUENCE:7
#EXTINF:3.984,
device1_audio_00007.ts
...
```

`Get-Process python` shows one `capture_audio_stereo_mix.py` and the
spawned `ffmpeg` writing to `device1_audio/segments/`; dashboard's
`<VNCAudioTrack>` chip lights up; clicking the chip un-mutes and
desktop audio plays in sync with the noVNC iframe.

## Companion fix (not in this commit, applied directly to vpt-pi4)

The vpt-pi4 nginx config had a regex block for the noVNC/websockify
subset of `/host/vpt-windows/` (already auth-gated), but the outer
prefix block (`location /host/vpt-windows/ { ... }`) had no
`auth_request` — so any other path under the host (the HLS
`/stream/.../output.m3u8` and `.ts`, the audio stream the dashboard
wants, etc.) returned 502 instead of 401 from anonymous curl. Added
`auth_request /server/host-session/authorize;` to that block,
`sudo nginx -t && sudo systemctl reload nginx`. Anonymous curl to the
audio m3u8 now returns 401; the dashboard works because the user has
the host-session cookie.

Backup: `/etc/nginx/sites-enabled/rpitest.conf.bak-pre-auth-20261017-195157`.
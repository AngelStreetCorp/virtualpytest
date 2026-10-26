# BUG-0605 — vpt-windows desktop audio never reached the dashboard (server built `stream_url` only)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0605                                                     |
| Reported  | 2026-10-17                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_server / frontend device control                     |
| Fixed in  | build 90145 |
| Commit    | `shortHash` (or "TBD")                                       |

---

## Symptom

After the capture pipeline was fixed (BUG-0604), the desktop audio HLS was live
and audible on the host (`-26 dB` mean while a sound played, playlist advancing
every 2 s), but the dashboard still played nothing and the browser log said:

```
[@hook:useStream] Audio Stream URL received: <none>
```

The `Host_Windows` tile had no `<audio>` element and no volume chip at all.

## Root cause

Two defects on the way from the device config to the browser.

1. **The server answered `getStreamUrl` without the audio URL.**
   `backend_server/src/routes/auto_proxy.py` has a server-side shortcut for
   `av/getStreamUrl` (it builds the URL from the registered host instead of
   proxying, to avoid a 504 when the host is busy). That shortcut called
   `buildStreamUrl()` only. The host's own `/host/av/getStreamUrl` (which does
   return `audio_stream_url`, BUG-0597) was never reached, so
   `useStream` always received `<none>` and `VNCStream` rendered no audio track.
   The shortcut also caches its response for 24 h, so a stale payload would
   survive even after a host-side fix.
2. **`buildAudioStreamUrl` mangled absolute paths.** It always prefixed
   `/host/<name>/` and always appended `/segments/output.m3u8`, so the
   vpt-windows value
   (`/host/vpt-windows/stream/device1_audio/segments/output.m3u8`) became
   `/host/vpt-windows/host/vpt-windows/stream/device1_audio/segments/segments/output.m3u8`
   — a 404 even once the URL was returned.
3. **Host registration dropped the field.** `register_host` in
   `backend_server/src/routes/server_system_routes.py` rebuilds each device
   from an explicit key whitelist; `audio_stream_path` was not in it, so the
   server's stored host (and every `getAllHosts` projection) never carried the
   audio path even though the host sent it.
4. **The Device Control tile is painted by `RecHostPreview`.** Its iframe comes
   from that component's portal (with the `_vpt`/`scale` transform), not from
   `DeviceStreamGrid`'s inline branch, and it had no audio track. The expanded
   stream modal (`RecStreamContainer`) already had one.
5. **The audio XHR carried no credentials.** The playlist is on the device
   server's origin behind nginx's host-session cookie; hls.js defaults
   `withCredentials` to false, so the manifest 401'd (`manifestLoadError`) and
   the track removed itself from the DOM. `HLSVideoPlayer` already set it.

## Fix

- `shared/src/lib/utils/build_url_utils.py` — `buildAudioStreamUrl` now accepts
  the three natural shapes and always returns the playlist once:
  `/host/<name>/.../output.m3u8` (used as written), `/stream/<device>_audio`,
  or `.../segments`. Verified for all five spellings (relative, absolute,
  with/without `output.m3u8`, with/without a leading slash).
- `backend_server/src/routes/auto_proxy.py` — the server-side shortcut imports
  `buildAudioStreamUrl` and adds `audio_stream_url` to the response (and logs
  it), matching the host route's contract.
- `backend_server/src/routes/server_system_routes.py` — `audio_stream_path` kept
  through `register_host` and both `getAllHosts` projections.
- `VncAudioTrack` extracted from `VNCStream` and mounted in
  `RecHostPreview` (Device Control tile) as well as `VNCStream`; the HLS
  instance sets `xhrSetup: xhr.withCredentials = true` like `HLSVideoPlayer`.

## Verification

- `buildAudioStreamUrl` unit-style check: every input shape resolves to
  `/host/vpt-windows/stream/device1_audio/segments/output.m3u8`; a device
  without `audio_stream_path` still returns `None`.
- After deploy, `GET /server/av/getStreamUrl?device_id=device1&host_name=vpt-windows`
  returns `audio_stream_url` next to `stream_url`.
- Headless browser on `/device-control`: the `vpt-windows` card mounts the
  audio chip (`console.log` shows `Audio Stream URL received: /host/vpt-windows/stream/device1_audio/...`);
  clicking it sets `muted: false` on the `<audio>` element, `readyState 4`,
  `currentTime` advances 3.03 s over 3 s. The source itself carries real
  sound (‑26 dB mean while a system WAV plays; BUG-0604).

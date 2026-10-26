# BUG-0587 — `apply_max_streams.py` writes device blocks without `_MODEL=rtsp_video` or `_STREAM_LOOP=1`, so the host registers the device with `av=None` and `/device-control` silently hides it

## Summary
`scripts/apply_max_streams.py` writes 6 env vars per device block (`NAME`,
`STREAM_TYPE`, `VIDEO`, `VIDEO_FPS`, `VIDEO_CAPTURE_PATH`, `VIDEO_STREAM_PATH`)
but is missing the 2 vars the host needs to populate the device's
`device_capabilities.av` field: `DEVICE<N>_MODEL=rtsp_video` and
`DEVICE<N>_STREAM_LOOP=1`. On nipogi, 8 of the 12 NEW devices ended up
registered to the backend with `av=None`, which the `/device-control` page
filters out. The host's 25 ffmpegs were running fine; the operator just saw
17 of 25 nipogi tiles on the dashboard. The remaining 8 (FR Kids 1/2/3, FR
Travel, FR Comedy, FR Series, FR Regional 3, FR Regional 4) were invisible.

## Repro
1. Run `apply_max_streams.py vpt-nipogi` on a fresh `backend_host/src/.env`.
2. The script writes lines like:
   ```
   DEVICE25_NAME=FR Kids 1 — Pluto TV Kids Classics FR (720p)
   DEVICE25_STREAM_TYPE=hls
   DEVICE25_VIDEO=https://jmp2.uk/plu-654a58dbf9cc82000868f0fb.m3u8
   DEVICE25_VIDEO_FPS=5
   DEVICE25_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture25
   DEVICE25_VIDEO_STREAM_PATH=/host/stream/capture25
   ```
3. `sudo systemctl restart vpt-host`. Wait for `✅ [HOST] Registration successful!`.
4. `curl -H "X-API-Key: …" https://<host-server>/server/system/getAllHosts | jq '.hosts[] | select(.host_name=="vpt-nipogi") | .devices[] | select(.device_capabilities.av==null) | .device_name'`
   lists 8 devices — every one written by the script.
5. The dashboard `/device-control` shows only 17 of 25 nipogi tiles, with
   pagination at the bottom (1 of 2). The 8 missing tiles live on page 2.

## Root cause
`backend_host` reads `DEVICE<N>_MODEL=` to decide the device's
`device_capabilities.av` value (`rtsp_stream` only if the model maps to one).
Without `MODEL=rtsp_video`, the device's `av` is `null` and the dashboard
hides it (per the `device_capabilities` filter in `DeviceGrid` / the
`/device-control` page). `STREAM_LOOP=1` is also needed to keep
`vpt-stream` looping the source after a stalled input. The original
`apply_max_streams.py` simply forgot to emit them in the
`new_block = [...]` and `append_lines += [...]` lists.

## Fix
- `scripts/apply_max_streams.py`:
  - `new_block` (REPLACE path) now emits `MODEL=rtsp_video` and
    `STREAM_LOOP=1` alongside `STREAM_TYPE=hls`.
  - `append_lines` (APPEND path) emits the same.
  - New "Pass 2.5": even when a NEW device is *already* in the file
    (REPLACE skipped it, or it was added by hand), the script now
    PATCHes missing `MODEL` / `STREAM_TYPE` / `STREAM_LOOP` lines. This
    lets you re-run the script on a host that already has broken blocks
    and recover — exactly the situation on nipogi 2026-10-17.
- `tests/scripts/test_apply_max_streams_av_block.py`: regression test
  that runs `apply()` against an in-memory `.env` fixture and asserts
  the REPLACE, PATCH and APPEND branches all emit the 8 required env
  vars per device (`NAME`, `MODEL`, `STREAM_TYPE`, `STREAM_LOOP`,
  `VIDEO`, `VIDEO_FPS`, `VIDEO_CAPTURE_PATH`, `VIDEO_STREAM_PATH`).
  1/1 green on Python 3.12.

## Recovery on a host that's already broken
```bash
# On the host, manually add the missing lines for the affected devices:
for n in 25 26 27 28 30 31 34 35; do
  if ! grep -q "^DEVICE${n}_MODEL=" /opt/virtualpytest/backend_host/src/.env; then
    sudo sed -i "/^DEVICE${n}_NAME=/a DEVICE${n}_MODEL=rtsp_video" /opt/virtualpytest/backend_host/src/.env
  fi
  if ! grep -q "^DEVICE${n}_STREAM_TYPE=" /opt/virtualpytest/backend_host/src/.env; then
    sudo sed -i "/^DEVICE${n}_MODEL=/a DEVICE${n}_STREAM_TYPE=hls" /opt/virtualpytest/backend_host/src/.env
  fi
  if ! grep -q "^DEVICE${n}_STREAM_LOOP=" /opt/virtualpytest/backend_host/src/.env; then
    sudo sed -i "/^DEVICE${n}_STREAM_TYPE=/a DEVICE${n}_STREAM_LOOP=1" /opt/virtualpytest/backend_host/src/.env
  fi
done
sudo systemctl restart vpt-host
curl -H "X-API-Key: …" https://<host-server>/server/system/getAllHosts \
  | jq '[.hosts[] | select(.host_name=="vpt-nipogi") | .devices[] | select(.device_capabilities.av==null)] | length'
# expect: 0
```

## How to verify on the dashboard
1. Open https://<host-server>/device-control (server picker already
   on vpt-pi4).
2. Total count next to "Device" reads `30 → 38` once the 8 devices become
   visible.
3. The `tv_lite` filter chip shows `21 → 29`.
4. Page 1 has 19 nipogi tiles (Anime 2/3/4, Comedy, Kids 1/2/3, Movie
   1/2 Polar/2 Vosges/3/4/6/7/8, Music, News 1/2/3). Page 2 has 6
   (Regional 3, Regional 4, Series MDL, Sport 1, Sport 3, Travel).
   Total: 25 nipogi tiles, all playing.

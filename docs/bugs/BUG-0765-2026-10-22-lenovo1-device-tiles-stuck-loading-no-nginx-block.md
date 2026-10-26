# BUG-0765 — Every vpt-lenovo1 device tile hung on "Loading stream..." because nginx had no `/host/vpt-lenovo1/` block

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0765                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | High (a whole host's device grid is unusable in the UI while the host itself reports healthy — 7 devices, all black) |
| Area      | infra / proxy / device tiles                                 |
| Fixed in  | — (internal) — config-only fix, hand-maintained `rpitest.conf` |
| Commit    | n/a — config-only fix, no repo change                        |

---

## Symptom

On the device page (server `vpt-pi4`), all seven `vpt-lenovo1` tiles stayed on
**"Loading stream..."** — or **"Snapshot unavailable"** before hover — while the
`vpt-nipogi` tiles on the very same page played normally:

```
Africa 24              Loading stream...        vpt-lenovo1
Africanews French      Loading stream...        vpt-lenovo1
BFM TV                 Loading stream...        vpt-lenovo1
CNews (iptv-org/...)   Loading stream...        vpt-lenovo1
FireTv                 Loading stream...        vpt-lenovo1
FR Anime 3             (playing)                vpt-nipogi
```

The host itself looked perfect, which is what made it misleading:

- `vpt-stream.service` active, ffmpeg running per device,
- `output.m3u8` present and rewritten every second,
- segments counting up (750 per 10 min on capture5/6/7),
- host registry: `status: online`, `last_seen` fresh,
- `curl http://192.168.1.26:6109/stream/capture5/segments/output.m3u8` → **200**.

So the host was healthy and the browser could not reach it.

## Root cause

Not a capture fault at all — a **missing nginx location block** on the server that fronts
the hosts (`vpt-pi4`).

Each host needs **two** proxy blocks: a regex block for noVNC assets (`:6080`) and a
prefix block for everything else — the stream, thumbnails and host API (`:6109`).
`vpt-lenovo1` only ever got the first one:

```nginx
location ~ ^/host/vpt-lenovo1/(vnc_lite\.html|websockify|vnc/|core/|vendor/|include/|app/|utils/) {
    proxy_pass http://192.168.1.26:6080;      # noVNC only
}
# ...and NO `location /host/vpt-lenovo1/ { proxy_pass http://192.168.1.26:6109; }`
```

Every other host in the same file has both (`vpt-pi4`, `vpt-nipogi`, `vpt-windows`,
`vpt-lenovo4/5/6`, `lenovo-local-hd`, `lenovo-local-low`, `vpt-wise1`). `vpt-lenovo1`
was added on 2026-10-15 with the noVNC block only.

So `/host/vpt-lenovo1/stream/...` matched no block and fell through to
`location / { proxy_pass http://127.0.0.1:5109; }` — the Flask backend, which has no such
route:

```
$ curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5109/host/vpt-lenovo1/stream/capture2/segments/output.m3u8
404
```

hls.js got a 404 for the playlist, so the tile sat on "Loading stream..." forever. The
thumbnails took the same route, which is why the snapshot mode said
"Snapshot unavailable" instead.

**Why the health checks did not catch it:** the server pings hosts by calling
`host_api_url` (`http://192.168.1.26:6109`) directly — never through nginx. The host was
online in the registry the whole time it was completely unreachable from the browser.

## Fix

Added the missing prefix block, modelled on the sibling hosts (note it keeps the
`/host/` prefix in the rewrite — the `:6109` API serves `/host/stream/...`, unlike the
`:6080` noVNC block which strips it):

```nginx
location /host/vpt-lenovo1/ {
    rewrite ^/host/vpt-lenovo1/(.*)$ /host/$1 break;
    proxy_pass http://192.168.1.26:6109;
    proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection $connection_upgrade;
    proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 3600; proxy_send_timeout 3600; proxy_buffering off;
}
```

`nginx -t` passed and nginx was reloaded. This file is hand-maintained — `update_core.sh`
never touches nginx and no repo script writes `sites-enabled` — so the fix survives
redeploys. Backup:
`rpitest.conf.bak-lenovo1-stream-20261022-103024`.

## Verification

Through ``<origin-host>``, before → after:

| Request | Before | After |
|---|---|---|
| `/host/vpt-lenovo1/stream/capture2/segments/output.m3u8` | 404 | **200**, 34953 B |
| `/host/vpt-lenovo1/stream/capture5/segments/output.m3u8` | 404 | **200**, 34953 B |
| `/host/vpt-lenovo1/stream/capture6/segments/output.m3u8` | 404 | **200**, 34953 B |
| `/host/vpt-lenovo1/stream/capture7/segments/output.m3u8` | 404 | **200**, 27978 B |
| `/host/vpt-lenovo1/stream/capture5/thumbnails/latest.jpg` | 404 | **200**, 7740 B |

No regression: `vpt-nipogi` stream still 200; the lenovo1 noVNC regex block still answers
(gated, 401 without a session cookie — correct).

In the real browser, hovering each tile:

| Tile | Before | After |
|---|---|---|
| BFM TV | Loading stream… (404) | **plays**, readyState 2, 320×180 |
| FireTv | Loading stream… (404) | **plays**, readyState 4 |
| Africanews French | Snapshot unavailable | **plays**, readyState 4 |
| Africa 24 | Snapshot unavailable | **plays**, readyState 4 |
| CNews | Loading stream… (404) | still 404 — see below |

## Also fixed here: CNews (DEVICE1) had a dead upstream

`CNews (iptv-org/Paradise-91)` was a **separate** fault, and stayed black after the nginx
fix. Its source was a **Dailymotion signed CDN URL** — a ~200-char token embedded in the
path — and those expire by design:

```
$ curl -o /dev/null -w '%{http_code}' "<DEVICE1_VIDEO manifest>"
403
```

so ffmpeg died immediately and the watchdog restarted it in a loop:

```
Oct 22 10:32:33  stream[1874]: ⚠️  device1: HLS ffmpeg exited after 1s — leaving the restart to the watchdog
```

`capture1` therefore had no `output.m3u8` at all, which is a legitimate 404 — nginx was
behaving correctly there.

**Replaced with BFM2 (CloudFront).** Candidates were re-probed from vpt-lenovo1's own FR
IP with the doc's real playability test (ffmpeg exits 0 **and** stderr empty — a 200 on a
manifest proves nothing, which is the trap that let this rot in the first place):

| Candidate | Result |
|---|---|
| **BFM2** (CloudFront, no UA needed) | **PASS** — chosen |
| Europe 1 TV (Paradise-91/ParaTV) | PASS — rejected, same fragile family that just died |
| Africa 24 English | PASS — rejected, duplicates a channel already on the host |
| BFM TV via `ncdn-live-bfm.pfd.sfr.net` | FAIL 404 (the UA problem above) |
| BFM Business (nextradiotv) | PASS |
| RMC Découverte | FAIL 403 |

BFM2 is national news (what CNews was), on a first-party CDN with no
`http-user-agent` dependency and no community-restream fragility.

Applied as a 2-line in-place `.env` edit (`DEVICE1_NAME` + `DEVICE1_VIDEO`; `STREAM_TYPE`
was already `hls`), every other line byte-for-byte preserved, backup at
`backend_host_src_.env.20261022-120216.pre-bfm2`. `vpt-stream` then `vpt-host` were
restarted — the **host** restart is what matters for the UI, because device names refresh
on host re-registration (`upsert_device_on_registration`), not on ping, and it also drops
the stale stream-URL cache. Verified in the browser: **BFM2 plays**, readyState 4, 320×180.

All seven `vpt-lenovo1` tiles now play.

## Prevention

- **Adding a host to a server means adding both blocks.** The noVNC `:6080` regex and the
  API `:6109` prefix are a pair; one alone produces a host that is online but unreachable
  from the UI. Worth a check whenever a new `location ~ ^/host/<name>/` appears without a
  matching `location /host/<name>/`.
- **A green host registry is not proof the browser can reach the host.** Health checks
  bypass nginx and go straight to `host_api_url`. "Host online + every tile black" should
  be read as *routing*, not *capture* — curl the stream URL **through the public origin**
  before looking at ffmpeg.
- **A running ffmpeg is not proof the source is alive.** "HLS ffmpeg exited after 1s" in
  `vpt-stream` means a dead source restart-looping, not a working capture. See
  [STREAMS.md](../agent/iptv-france-streams/STREAMS.md) for the signed-URL expiry class
  and how to re-probe a replacement.
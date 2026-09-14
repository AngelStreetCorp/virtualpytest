# Stream & Monitor optimizations (host)

What was wrong with the `vpt-stream` (`run_ffmpeg.sh`) and `vpt-monitor`
(`capture_monitor.py`) pipelines, what was changed, and why — so it is
understood later and not "re-optimized" in the wrong place.

Investigated & fixed 2026-05-19. Re-profile any time with
**[../../scripts/PROFILING.md](../../scripts/PROFILING.md)**
(`scripts/profile_remote_monitor.sh <host>`).

> **TL;DR ordering rule:** these symptoms cascade —
> *broken watchdog → constant ffmpeg restarts → counter resets → frontend
> "stuck" + fake freezes + unbounded monitor chunk*. If stream/monitor
> misbehave, diagnose in this order and read this doc first. The CPU-heavy
> part of the monitor was **JSON chunk I/O, not the CV detection** — do not
> "optimize" `detector.py`; it is ~10–35% and legitimate.

---

## Stream — `run_ffmpeg.sh`

### 1. Watchdog liveness signal (`8068676b4`)

`check_grabber_health` decides ffmpeg is alive from
`/tmp/ffmpeg_output_<id>.log` **mtime**. ffmpeg runs with
`-loglevel error -stats`; a *healthy* stream emits only the `-stats`
progress line, which is **carriage-return (`\r`) terminated**. stderr is
piped through line-oriented `grep` (noise filter), which never emits a
`\r`-only "line" → the log stayed **0 bytes, mtime frozen on a healthy
stream** → the watchdog declared every healthy grabber "stale" and
killed+restarted it. Measured: **~90 needless restarts / 30 min / host**.

**Fix:** `2> >(stdbuf -oL tr '\r' '\n' | grep -v --line-buffered … )`.
Each stats refresh becomes a real line so the log mtime advances ~1/s as
the watchdog assumes. **The `tr '\r' '\n'` is load-bearing — do not remove
it** (comment in the script says so).

### 2. Continuous segment / capture numbering (`351e681ad`)

Every ffmpeg (re)start reset the `segment_%09d.ts` and `capture_%09d.jpg`
counters to 0. Consequences of a counter rewind:
- browser HLS.js 404s the old high-numbered segments → "FFmpeg appears
  stuck. Stream restart required." / perpetual "Loading stream";
- `capture_monitor`'s LIFO backlog guard mis-reads the jpg rewind as a
  huge backlog and never closes the freeze incident → **fake multi-hour
  freeze** (e.g. irstb "Freeze: Yes 63782 s").

**Fix:** `next_start_number()` resumes each counter from
`max(existing index)+1` via `-start_number` on the HLS + capture +
thumbnail muxers (all four source paths), then prunes the now-orphaned
prior files (RAM tmpfs would otherwise leak a run's worth per restart).
Fail-safe: no/garbage files → start 0 = old behaviour. `%09d` is
min-width (no wrap); counter is 64-bit (no practical ceiling).

### 2b. Segment counter is the single source of truth — captures DERIVE from it

**Superseded the per-counter resume above for the image muxers.** Resuming
the segment counter and the capture counter *independently* (each from its
own dir's `max+1`) hid a latent desync. The `getSegmentCapture` API maps a
segment to its still frame arithmetically:

```
capture_number = segment_number * fps        # shared/.../storage_path_utils.py
```

which only holds while the two counters stay locked at exactly that ratio.
The moment one branch lost its files while the other survived — e.g. the
mjpeg capture output dying on a VAAPI encode crash while HLS segments
persisted — `next_start_number` resumed segments at e.g. `83224` but
captures at `0`. From then on the counters were offset by ~416 k and
**every `getSegmentCapture` returned 500** ("Capture … not found in hot or
cold storage").

**Fix:** make **segments authoritative** and *derive* the capture/thumbnail
start numbers:

```bash
cap_start  = seg_start * captures_per_segment   # 5 v4l2 · 8 x11grab · input_fps ADB/image
thumb_start = cap_start
```

`captures_per_segment = capture_fps * hls_segment_seconds`. The API
invariant now holds **by construction** and cannot desync regardless of
what's in the captures dir. The prune now runs **unconditionally**, so if
segments ever reset to 0 the stray captures are cleared too, forcing a
clean resync of both counters from zero. A drifted host self-heals on the
next `vpt-stream` restart — no manual hot-storage wipe needed.

Note: macOS / Windows `run_ffmpeg` reset both counters to 0 every restart
(no `-start_number` resume), so they never had this drift — Linux-only fix.
If VNC (x11grab) screenshots ever 500, check that the frontend passes
`fps=8` (its `captures_per_segment`), since x11grab uses 4 s segments.

### 2c. Per-branch frame rate — native video, 5 fps stills

Originally the v4l2 filter graph decimated the **whole** pipeline up front
(`[0:v]fps=5[v5];[v5]split=3…`), so the HLS stream, captures and thumbnails
were *all* capped at 5 fps — a choppy stream even when the source delivered
more. The decimation belongs **per branch**, after the split:

```
[0:v]split=3[str][cap][thm];
  [str]scale=…[streamout];                 # VIDEO: no fps cap → native input rate
  [cap]fps=5,scale=…[captureout];          # STILLS: 5 fps (plenty for detection)
  [thm]fps=5,scale=…[thumbout]
```

- **Stream** runs at the input rate (`DEVICE${i}_VIDEO_FPS`, the v4l2
  `-framerate`). To raise smoothness, raise that env — do **not** remove
  `-framerate` on the MS2109 dongles (they negotiate a bad mode without it).
- **Captures / thumbnails** stay 5 fps. `fps=5` is placed *before* `scale`
  so only 5 frames/s are scaled — keeps the image branches' CPU ~unchanged.
- `captures_per_segment` in §2b = still_fps × segment_seconds (v4l2: 5 × 0.4 =
  **2**, see §2f). If you change the still fps OR the segment duration, recompute
  it (and keep the frontend's `fps` arg = still fps).
- Same split-first structure applies to x11grab (VNC): captures `fps=5`, stream at
  the input rate (`HOST_VIDEO_FPS`); see §2f for its 1 s segments.

### 2d. VAAPI hardware H.264 encode (offload the stream off CPU)

Uncapping the stream (2c) raises encode cost, so on Intel/AMD hosts we
offload the **HLS stream** branch to the iGPU. `detect_vaapi()` runs once at
startup (result cached in `/tmp/vpt_vaapi_render_node`) and sets it up only
when a render node with a real H.264 **encode** entrypoint exists:

```
/dev/dri/renderD128 present + vainfo shows VAProfileH264*:VAEntrypointEncSlice
  → -vaapi_device … ; [str]…,format=nv12,hwupload ; -c:v h264_vaapi
else (e.g. Raspberry Pi 5 — VideoCore VII has NO H.264 encoder)
  → -c:v libx264 -preset ultrafast   (unchanged software path)
```

Hard-won details:
- **Only the stream branch is uploaded.** Capture/thumbnail mjpeg stay on
  CPU (image2 needs software frames). Don't `hwupload` before the `split`.
- **Profile matters:** iHD throws `internal encoding error 24` on
  `constrained_baseline`. Use the default **High** profile (`-c:v h264_vaapi
  -b:v … -g 4`); that's what the validated standalone test used. `-g` = the GOP
  length and must equal `stream_fps × segment_seconds` (10 × 0.4 = 4, see §2f) so
  every segment starts on a keyframe.
- **Coupling risk:** stream + stills share one ffmpeg process, so a VAAPI
  encode fault kills the capture mjpeg too (→ the §2b desync). Watch
  `journalctl -t stream` for `error 24` under sustained N-device load — the
  iGPU's concurrent-encode-session limit is the next ceiling to validate.
- Host prep (Intel example, Debian needs `non-free`):
  `apt install intel-media-va-driver-non-free vainfo`. libva auto-selects
  iHD/radeonsi from the PCI id — we do **not** force `LIBVA_DRIVER_NAME`.
  `vainfo` is **not** in the host installer, so VAAPI never auto-activates
  on a host until someone installs the driver+vainfo there.
- To force the software path without redeploy: `> /tmp/vpt_vaapi_render_node`
  then restart. To re-probe after install: `rm` that file then restart.

### 2e. Audio probe needs `arecord` (alsa-utils)

Each grabber probes its audio device with `arecord` before adding the
`-f alsa` input. If `arecord` is missing, **every** probe fails and all
devices silently start **video-only** — which looks exactly like an
audio-device fault, not a missing package. `alsa-utils` is now in the host
installer, and `run_ffmpeg.sh` warns loudly once at startup when `arecord`
is absent. (ALSA card naming is separate — see
`docs/agent/devices/PERSISTENT_DEVICES.md` for the `plughw:stbN,0` udev scheme.)

### 2f. Live HLS latency — 0.4 s segments + player catch-up

Live video showed ~4–5 s glass-to-glass. We measured the pipeline and the
**server is real-time** (newest segment 0 s old, playlist served fresh, Cloudflare
`cf-cache-status: DYNAMIC` = not cached). The latency is structural to HLS:

```
glass-to-glass ≈ segment-completion-delay + player-holdback
              = (a frame waits for its segment to finish)  +  (player sits N segments behind the live edge)
```

Two levers, both shipped:

- **Server — `hls_time 1 → 0.4` (v4l2 only).** Halving+ the segment cuts the
  completion delay (~1 s → ~0.4 s) *and* lets the player sit stably closer. Keyframe
  cadence must follow: `keyint`/`-g` = `stream_fps × 0.4` = **4** (§2d), and
  `captures_per_segment` = **2** (§2b/§2c). **Captures stay 5 fps** — they are a
  separate filter branch (§2c), so the 200 ms freeze-detection granularity is
  unchanged. Constraint: `still_fps × segment_seconds` must be an integer, so the
  duration must be a multiple of **0.2 s** (0.4 ✓, 0.5 ✗ → 2.5). The archiver is
  duration-agnostic — it reads the real duration from the m3u8 `#EXTINF` median and
  computes `segments_needed = round(60/duration)` (`hot_cold_archiver.py`); the
  `get_device_segment_duration()` fallback also reads the m3u8 now.
- **Player — hls.js live config** (`frontend/.../HLSVideoPlayer.tsx`): the missing
  piece was **`maxLiveSyncPlaybackRate` (1.5)**. Without it (default 1.0) hls.js only
  corrects drift by *seeking* once it passes `liveMaxLatencyDuration`, so latency
  oscillated up to that cap; with it, hls.js gently speeds up to *glide* back to the
  edge. Plus `liveSyncDuration 1.5`, `liveMaxLatencyDuration 4`.
- **Playlist cache header** (`host_stream_routes.py`): the live `.m3u8` must be
  `no-cache` (only the immutable `.ts` may cache). It was lumped with `.ts` at
  `max-age=30` — a stale playlist would add up to that many seconds for every player.

Result: **~4–5 s → ~2.5–3 s** glass-to-glass, with **flat ffmpeg CPU** (more/smaller
keyframes are ~free at `ultrafast` on a 320×180 stream) and no detection or archiver
impact. Floor for plain HLS is ~2.5 s — below that needs true LL-HLS (fMP4 + parts;
ffmpeg's `-lhls 1` emits **no** `EXT-X-PART`, verified) or WebRTC.

> **VNC/x11grab** uses the same optimization but at **1 s** segments (`hls_time 1`,
> `captures_per_segment 5`, captures `fps=5`, `keyint=$input_fps` → a clean 1 s GOP at
> any fps). 1 s (not 0.4 s) because 0.4 s needs `input_fps × 0.4` integer (fps 5/10
> only). **Requirement: `HOST_VIDEO_FPS >= 5`** — captures are pinned to 5 fps, so a
> lower input *upsamples* them (duplicate frames → false freeze). `.env.example`
> default is now **10**; **existing VNC hosts still on fps 2 must be raised to >= 5**
> (per-host `.env`) when this deploys, or freeze detection will misfire. VNC can also
> carry desktop audio (`HOST_VIDEO_AUDIO=default`).

---

## Monitor — `capture_monitor.py`

### 3. Counter-reset guard in `_add_event_duration_metadata` (`8172784e9`)

Defence-in-depth for #2: detect a large backward jump in capture sequence
(an ffmpeg restart) vs. a small LIFO reorder, resync
`last_processed_sequence`, and drop stale `*_event_start` state across the
discontinuity so a single stall can't become a permanent fake freeze.
Now mostly redundant given #2, kept as a safety net.

### 4. Chunk write coalescing (`ce57fd497`)

`_append_to_chunk` did a full `json.load` + `sort` + `json.dump(indent=2)`
of the **entire** 10-min chunk file **on every frame**. py-spy attributed
**~43 % of monitor CPU** to this (the actual CV detection was only ~7 %).

**Fix:** keep the chunk in memory, append `O(1)`, and flush to disk at
most every 2 s, on 10-min rollover, and on shutdown — reusing the existing
2 s stall-watcher tick (no new thread). On-disk format unchanged except
`indent` dropped (machine-read by zap_executor). Brought monitor CPU
49 % → 33 %, but the residual was still ~25 % because `N` was huge…

### 5. Stale 10-min slot rotation — THE root cause (`22d465fa6`)

`calculate_chunk_location()` (in `shared/.../storage_path_utils.py`,
**centralized for metadata *and* MP4**) returns `(hour, chunk_index)` with
**no date**. So `metadata/{hour}/chunk_10min_{idx}.json` is reused **every
day**. The original `_append_to_chunk` did `if exists: json.load →
append`, so it resumed *previous days'* files instead of overwriting them
as the design intends (`hot_cold_archiver`: *"files naturally overwrite
after 24h"*). Result on disk: one "10-minute" file held **11,125 frames
spanning 26 days**; **~1.5 GB** of metadata bloat across host1+host3.
That unbounded `N` — *not* the frame rate (5 fps, the `%5` gate correctly
yields ~1/s ≈ 600/day) — is what kept the flush `O(N)` expensive.

**Fix:** resume an existing chunk only when its last timestamp is the
current date; otherwise start fresh. Restores the intended per-slot
rotation, bounds `N` to ~600, **no path/reader changes**.

---

## Measured result (host1, identical py-spy methodology)

| Metric | Baseline | After #4 | **After #5 + clean reset** |
|---|---|---|---|
| `capture_monitor` CPU | ~49 % core | 33 % | **17.9 %** |
| py-spy samples / 30 s | 5076 | 3134 | **1370** |
| chunk/JSON in profile | ~43 % | ~25 % | **0 %** |
| chunk `N` | 11 k, **unbounded** | 11 k | **~600, bounded, single-day** |
| box load (1 m) | ~3.6 | ~3.9 | **~2.2** |

Load fell more than the CPU saving alone because the unbounded chunk also
caused heavy **disk-write / I/O-wait churn** (rewriting multi-MB files
every 2 s × N devices); eliminating it removed CPU *and* iowait.

**An append-only / JSONL chunk format was evaluated and rejected:** after
#5, chunk/JSON is 0 % of the profile — nothing left to gain, and it would
break the centralized chunk format for every reader. Don't.

---

## Operating notes

- Existing oversized chunk files **self-heal within 24 h** as each slot
  next rotates. To reclaim immediately (per host):
  ```bash
  sudo systemctl stop vpt-monitor
  sudo find /var/www/html/stream/capture*/ -path '*/metadata/*' \
       -name 'chunk_10min_*.json*' -type f -delete      # NEVER touch capture_*.json
  sudo systemctl start vpt-monitor
  ```
  Only `chunk_10min_*` aggregates — the per-frame `capture_*.json` files
  are the frontend's live source (`/server/monitoring/latest-json` reads
  the newest one) and must not be deleted.
- `vpt-stream` and `vpt-monitor` are **separate units**. A code deploy
  needs the matching service restarted; restarting `vpt-stream` does not
  reload the monitor and vice-versa.
- Re-profile after any change to these paths:
  `scripts/profile_remote_monitor.sh <host> vpt-monitor 30 240`.

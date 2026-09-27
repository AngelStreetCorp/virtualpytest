# BUG-0169 — Emulator streams went black after ~17 minutes: the image outputs starved the audio input

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0169                                                     |
| Reported  | 2026-09-27                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host (`run_ffmpeg.sh`, imagefile / emulator capture) |
| Fixed in  | Unreleased                                                   |
| Commit    | `f85e19817`                                                  |

Follows [BUG-0165](BUG-0165-2026-09-27-emulator-stream-stalls-on-duplicate-capture-timestamps.md). Once that
stall was fixed, a stream finally reached the browser and this problem became visible. Both come
from `1d3581ffe` ("the emulator's own sound reaches the host", build 9151).

---

## Symptom

On `/device-control` the emulator tiles (`labox-mobile`, `labox-dongle`'s `labox-tv`) played after a
restart of `vpt-stream`, then went black 15–20 minutes later. Other devices on the same page kept
playing. Everything on the host looked healthy: `latest.png`, captures, thumbnails and HLS
segments were fresh, and a decoded segment frame had the right picture. Every playlist and segment
request returned `200`.

In the browser, the `<video>` element kept advancing `currentTime` but stayed at `readyState 1` and
never decoded a frame. `ffprobe` on a segment showed audio and video on different timelines. How far
apart, and in which direction, depended on how the audio was stamped:

| Audio stamping | What the drift looked like |
|---|---|
| PulseAudio input's own stamps (`1d3581ffe`) | audio ran ~95,000 s (26 h) *ahead* within 2 h |
| Sample count, `asetpts=N/SR/TB` | audio fell 1.4% *behind* from ~minute 17 |
| Arrival wall clock + `aresample` | audio fell ~1.2% *behind* from ~minute 17 (-34 s at 66 min) |

## Root cause

ffmpeg reads its inputs only as fast as its **slowest output** advances. The emulator pipeline
has three video outputs from one `split=3`: the HLS stream and two JPEG outputs (captures and
thumbnails, `-fps_mode passthrough`). `1d3581ffe` put only the stream on the wall clock
(`settb=AVTB,setpts=RTCTIME-RTCSTART`). The JPEG outputs stayed on the synthetic input clock, frame
N at N/5 s. The `cat` loop feeding the frames delivers about 4.93 of the declared 5 fps, so that
clock runs about 1.4% slower than real time. ffmpeg pulled the PulseAudio input at the same slow
pace.

For about 17 minutes the audio input's queue (`-thread_queue_size 2048`) absorbs the backlog. Then
it is full, samples are lost, and the audio timeline slips away from the video one. How it slips
depends only on the stamping (table above), which is why changing the audio timestamps never fixed
it.

Proof, on the same host with the same source and the same PulseAudio server: three copies of the
pipeline were run side by side in `/dev/shm`.

| Copy | Gap at 15 min | Gap at 20 min |
|---|---|---|
| Exact production command | 0.02 s | -1.57 s |
| Same, audio buffer 100 ms × 4096 packets | 0.02 s | -1.71 s |
| Same, **without the two JPEG outputs** | 0.01 s | **0.02 s** |

Ruled out along the way: PulseAudio delivery (60 s with `parec` and with ffmpeg's own pulse input,
48 kHz or 44.1 kHz, all 1.0006–1.0016× real time, no server-side backlog), the stderr filter pipe,
CPU quota/throttling (none), CPU steal (2–4%), clock steps, and the hot RAM storage (14% used).

## Fix

`backend_host/scripts/run_ffmpeg.sh`, imagefile branch:

- The wall clock (`settb=AVTB,setpts=RTCTIME-RTCSTART`) moves in front of `split=3`, so all three
  video outputs advance in real time and none of them holds the audio input back.
- Both JPEG outputs get `-enc_time_base 1:1000`. Without it, two wall-clock frames inside one
  1/5 s tick share a pts and mjpeg stalls ffmpeg (BUG-0165, the reason the clock had been moved off
  these outputs). `-enc_time_base -1` is not enough: it falls back to the input's 1/5 s base.
- The audio input keeps `-use_wallclock_as_timestamps 1` and `-af aresample=async=1000:first_pts=0`,
  so small jitter in PulseAudio delivery is still absorbed.

## Verification

- Before: the replica table above; in production, -9 s at 30 min and -34 s at 66 min, tiles black.
- 30-second test of the fix: 5 fps captures (138 in ~28 s), 25 segments, gap 0.01 s, 0 pts errors,
  captures show the real picture.
- Deployed to both emulator hosts at 19:42. The tiles play (`readyState 4`, frames drawn). A
  30-minute production soak checks the gap and pts errors every minute, past the ~17-minute onset.

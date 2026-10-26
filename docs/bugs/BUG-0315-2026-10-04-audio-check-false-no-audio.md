# BUG-0315 — Audio reported missing on devices that had sound (half-second probe, mean level, timeouts)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0315                                                     |
| Reported  | 2026-10-04 (heatmap audio column on a 24-device HLS host)    |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — false audio-loss in heatmap, KPIs and alerts        |
| Area      | `backend_host/scripts/transcript_accumulator.py` (audio detection worker) |
| Fixed in  | build 90145 |
| Commit    | `6386679964`, `4d9853e009`                                   |

---

## Symptom

On a host playing Apple's bipbop test streams, every bipbop device showed "No" audio at -91 dB
for 6–8 minutes, then "Yes" for about 10, all at the same moments, although the stream audibly
beeps. A film source (Big Buck Bunny) showed "No" at -56 dB during quiet scenes. On a busy
host, single devices flipped to "No" at -100 dB.

## Root cause

Three rules in the per-device audio probe:

1. It measured only the first 0.5 s of each segment (`-t 0.5`). Bipbop's sound comes in bursts,
   and the audio drifts against the segment boundary (about 2.7 ms per 1 s segment). Whenever the
   half-second fell in the gap between beeps, the probe read digital silence (-91 dB) while the
   whole segment was at -21 dB. The archived recording had no silence at all (`silencedetect`
   over the same 10-minute chunks found none).
2. It decided on the **mean** volume (`> -50 dB`). Quiet film scenes average -50..-70 dB while
   peaking at -25..-45 dB.
3. A probe that timed out (2 s, CPU-bound host) was recorded as audio lost at -100 dB.

## Fix

- Measure the whole segment (0.4–1 s) and decide on its **peak**: `max_volume > -60 dB`. Lost
  audio is digital silence, -91 dB on both peak and mean. `mean_volume` stays the reported level.
- A timed-out probe keeps the device's last measured state (or N/A when there is none).

## Verification

- Same segment, before/after: first 0.5 s mean/max -91.0/-91.0 dB, whole segment -21.0/-2.7 dB.
- After deploy on the 24-device host, all five bipbop devices: 27/27 checks "Yes" through the
  window where they had previously gone silent. The only remaining "No" readings were two probe
  timeouts (fixed by the second commit) and one real silent passage of the film (-79.5 dB peak).

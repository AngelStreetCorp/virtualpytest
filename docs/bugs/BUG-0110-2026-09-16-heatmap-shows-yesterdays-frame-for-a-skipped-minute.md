# BUG-0110 — A skipped minute showed yesterday's heatmap, while the Dashboard said the service was fine

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                        |
|-----------|-------------------------------------------------------------------------------|
| ID        | BUG-0110                                                                        |
| Reported  | 2026-09-16                                                                      |
| Status    | **Fixed (pending deploy).**                                                      |
| Severity  | Medium (a stale mosaic passed off as the current minute; the two pages disagreed) |
| Area      | `frontend/src/hooks/useHeatmap.ts` · `frontend/src/components/MosaicPlayer.tsx` · `backend_server/scripts/heatmap_processor.py` · `backend_server/src/routes/server_system_routes.py` |
| Fixed in  | build 9151                                                                                                                                                                            |

---

## Symptom

Two pages told two different stories at the same moment:

- **Monitoring → Heatmap** showed *"Heatmap data may be outdated. The backend processor
  might not be generating new data."* — and, underneath the banner, a full mosaic.
- **Dashboard → Server Services** showed **Heatmap `active`**, with no error anywhere.

The mosaic on screen was not the current minute. Its header read *Today 07:16 · Devices 5*
while the processor was, at that exact moment, generating frames for **6** devices.

## Root cause

Heatmap files are a 24h circular buffer named by **HHMM only** — `heatmaps/<server>/0716.json`
is overwritten once a day. So a minute the processor skips does not leave a gap: it leaves
**yesterday's file** sitting at that name.

At 07:16 the processor skipped one minute:

```
07:15:00  Generated heatmap for 0515 (6 devices)
07:16:00  Processing heatmap for 0516
07:16:00  Error getting hosts from API: HTTPConnection(host='localhost', port=5109):
          [Errno 111] Connection refused
07:16:00  No hosts available for 0516          ← returns early, writes nothing
07:17:01  Generated heatmap for 0517 (6 devices)
```

`vpt-server` runs a **single gevent worker** (deliberately — it talks to the DB over WAN), so
one worker restart makes exactly one call fail, and the processor gave up on that minute at
the first refusal.

The page then loaded `0516.json` — yesterday's, from when the fleet had 5 devices — and
handled it in the worst possible way:

- Its freshness test was `ageInHours > 24`. Yesterday's file at the *same* HHMM is barely
  over 24h old, so the test tripped, which is why the banner appeared.
- But tripping the test only set a flag. `setAnalysisData(data)` ran regardless, so the
  rejected frame was rendered anyway — banner on top, yesterday's mosaic below.
- The banner's wording ("the backend processor might not be generating new data") accused
  the backend of an outage over a single missing minute.

Meanwhile the Dashboard asked `systemctl is-active vpt-heatmap`, which answers for the
*unit*, not for its output. A processor that runs every minute and produces nothing — no
hosts, failing uploads, as in [BUG-0109](BUG-0109-2026-09-16-failed-incident-insert-uploads-a-million-orphan-thumbnails.md)
— reads `active` all the way through the outage.

## Fix

**Never show another minute's frame.** A frame is accepted only when its timestamp sits
within 5 minutes of the slot it was fetched for; a previous-day leftover is treated exactly
like a missing file (walk back, then report nothing). `MosaicPlayer` takes the slot the data
actually came from, so it can no longer paint a mosaic the loader rejected — the "no data"
state shows no image at all, rather than a picture with a warning above it.

**Say what is actually missing.** The banner now names the minute and points at the
Dashboard if the hole is bigger than a minute or two, instead of declaring the backend
broken. The header names the frame on screen (the loader may fall back a few minutes).

**Make the Dashboard report output, not just uptime.** The processor writes each minute's
outcome to `/tmp/heatmap_status.json` (`last_success`, `last_time_key`, `last_error`), and
`_build_server_service_health()` turns the Heatmap chip to `stuck` when no frame has been
produced for 3 minutes, with the reason in its tooltip. A running-but-silent processor now
looks wrong in the same place the user would look.

**Stop punching the hole in the first place.** `get_hosts_devices()` retries 3 times, 3s
apart, so a worker restart costs a retry instead of a minute.

## Verification

- `tests/frontend/Heatmap.test.tsx` — the page reports a missing frame for the selected
  minute, and says nothing when the frame is good.
- On the server: `python3 -c "import json;print(open('/tmp/heatmap_status.json').read())"`
  tracks the current minute; stopping `vpt-heatmap` for 3 minutes flips the Dashboard chip
  to `stuck`, and restarting it flips it back.

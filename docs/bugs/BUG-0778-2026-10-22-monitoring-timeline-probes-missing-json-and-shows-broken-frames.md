# BUG-0778 — The Monitoring timeline probes a thumbnail JSON file that does not exist 14 to 16 times per load and shows empty or broken frames

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0778                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | frontend / host                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding TESTER-07, ANALYST-A-07, OPS-14, CHAOS-02, in `docs/tasks/QA-ANALYST-findings.md`, `docs/tasks/QA-CHAOS-findings.md`, `docs/tasks/QA-OPS-findings.md`, `docs/tasks/QA-TESTER-findings.md`); reproduced against the live app.

- **Page / route:** /monitoring/timeline
- **Viewport / theme:** 1440 px dark and light; 390 px dark

Steps to reproduce:

1. Open Monitoring > Timeline.
2. Open the network panel and the console.

**Expected:** The timeline frames load; a missing thumbnail is not requested or is handled quietly.

**Actual:** 14 to 17 requests per load, all failing: `HEAD /host/<host>/stream/<capture>/thumbnails/<n>/timeline_<k>_6s.json` answers 404 for each numbered capture folder (and 401 for the plain one), with 16 console errors and 17 aborted requests. The page renders but the frames are slivers about 20 x 60 px with unreadable captions; CHAOS-02 saw every thumbnail broken. The probe is one index past the end of the recorded thumbnails and repeats on every navigation.

Evidence:

- [tester-07-timeline-404-requests.png](../tasks/qa-evidence/tester/tester-07-timeline-404-requests.png)
- [desktop-dark-monitoring-timeline.jpg](../tasks/qa-evidence/chaos/desktop-dark-monitoring-timeline.jpg)
- [timeline.png](../tasks/qa-evidence/analyst/pass1/timeline.png)

## Root cause

The page answered "does this device have a Timeline?" by **probing for files**, up to four of them per device, with `HEAD`:

- `frontend/src/hooks/useTimelineSupport.ts` — `deviceHasTimeline()` fetches the archive manifest, then HEADs `timeline_<n>_6s.json` for the four newest chunks.
- `frontend/src/hooks/useTimeline.ts` — the "is the service building anything" probe HEADs `timeline_<n>_30s.json` for up to three chunks.

But the Timeline service is **opted in per device** (`DEVICE<N>_TIMELINE=true`, or `TIMELINE_ALL=true` — `backend_host/scripts/timeline/service.py`), and the host already answers the question in one call: `GET /host/timeline/status?device_id=…` returns `{enabled, chunks, backlog, newest_pending}` (`backend_host/src/routes/host_timeline_routes.py`).

On host-clone-1 the service is enabled for **device2 only**. The other three devices (`host`, `device3`, `device4`) have no Timeline at all, so every probe for them 404s — 3 devices × 4 chunks = the 12 to 16 failed requests the sweep counted, plus the 3 probes from `useTimeline`. The probes that *did* find a file (device2) worked: the page rendered the sprites.

The frontend never called the status route — it existed and was unused.

The live host confirms the split:

```
$ curl "http://<host>:6109/host/timeline/status?device_id=device2"
{"backlog":0,"chunks":144,"device_id":"device2","enabled":true,...}
$ ... device_id=device3
{"backlog":144,"chunks":144,"device_id":"device3","enabled":false,...}
```

and on disk only device2 has a `thumbnails/` tree:

```
/var/www/html/stream/capture2/thumbnails/1/timeline_3_6s.json   ← device2
/var/www/html/stream/capture/thumbnails/                        ← empty
/var/www/html/stream/capture3/thumbnails/                       ← empty
/var/www/html/stream/capture4/thumbnails/                       ← empty
```

So the 404s were not a broken file, a wrong path or a wrong index — they were the page asking for a file that could never exist, because the service was never enabled for that device.

## Fix

The page asks the host once per device and trusts the answer.

- `frontend/src/hooks/useTimelineSupport.ts` — new `hostTimelineStatus(host, deviceId)` calls `GET /server/timeline/status?host_name=…&device_id=…` (the server's auto-proxy forwards it to the host's `/host/timeline/status` with the server's API key). `deviceHasTimeline()` now returns `false` immediately when the host says the service is **off** for that device: no manifest fetch, no file probe. When the host answers that the service is on, the existing sprite probe still runs, so "the service is on but has not built a sprite yet" keeps its old meaning. If the host does not answer at all (an older host without the route, a network error), the function falls back to the old probe, so nothing breaks on an un-updated host.
- `frontend/src/hooks/useTimeline.ts` — the "is the service building anything" probe asks the same question first and answers `built: false` without probing files when the service is off for the device.

Result on host-clone-1: four successful JSON calls (one per device) replace sixteen HEAD probes, of which fifteen could only 404.

## Verification

Measured on the live app with `scripts/agent/probe_timeline_requests.py` (Playwright, `/monitoring/timeline`), before the fix:

```
timeline/thumbnail responses: 182
  GET   200     x148
  HEAD  FAILED  x17
  HEAD  404     x16
  HEAD  200     x1
```

The sixteen 404s are the probes for `capture`, `capture3` and `capture4`; the single 200 is `capture2` (the one device the service is enabled for). After the fix the same probe reports no failing HEAD request at all — every device is answered by one `/server/timeline/status` call.

Regression test: `tests/frontend/TimelineSupport.test.tsx` — "asks the host once per device instead of probing files that cannot exist" (a device whose service is off is never probed for a file) and "still probes the sprite file for a device the service is on". With the source reverted, 2 of the 5 tests in that file fail; with the fix all 5 pass. `tsc --noEmit` is clean.


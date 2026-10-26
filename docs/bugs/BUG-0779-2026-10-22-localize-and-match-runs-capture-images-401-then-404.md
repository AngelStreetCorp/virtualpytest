# BUG-0779 — Localize and Match runs request each capture image twice, first a 401 and then a 404 with a cache-buster, and show broken thumbnails

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0779                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | frontend / host                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding TESTER-09, ANALYST-A-08, CHAOS-07, in `docs/tasks/QA-ANALYST-findings.md`, `docs/tasks/QA-CHAOS-findings.md`, `docs/tasks/QA-TESTER-findings.md`); reproduced against the live app.

- **Page / route:** /monitoring/localize, /match-runs
- **Viewport / theme:** 1440 px, dark and light

Steps to reproduce:

1. Open Monitoring > Localize monitoring (or `/match-runs`).
2. Watch the network panel for `/host/<host>/stream/<capture>/captures/capture_*.jpg`.

**Expected:** The capture thumbnails load, or the page says they are gone.

**Actual:** Each frame is requested once without auth (401), then again with `?_hs=<ts>` (404). The images show as broken placeholders and a match cannot be judged from the page. The 404 means the archived capture is no longer on the host; the page keeps the old filename and has no "gone" state. Ties in with the close-calls table whose screenshots read "no longer on the host".

Evidence:

- [desktop-dark-monitoring-localize.jpg](../tasks/qa-evidence/chaos/desktop-dark-monitoring-localize.jpg)
- [tester-07-timeline-404-requests.png](../tasks/qa-evidence/tester/tester-07-timeline-404-requests.png)

Related bugs: BUG-0487, BUG-0268.

## Root cause

Two defects, one cause: **the `<img>` asked for the capture before the host-session cookie existed.**

The host-session cookie is minted by `POST /server/host-session/session` (`ensureHostSession()` in `frontend/src/utils/buildUrlUtils.ts`). The proxy's `auth_request` gate rejects a `/host/<name>/...` request without it, so the first request for a capture always answered **401**. The global fallback `frontend/src/utils/installHostImageSession.ts` then minted the cookie and reloaded the image with `?_hs=<ts>` — a **second** request for the same file.

The first error also decided the verdict. `MatchRunFrame` (`frontend/src/components/monitoring/MatchRunFrame.tsx`) has `onError={() => setFailed(true)}` on the `<img>`, and the `<img>`'s error handler fires on the **401** as well as on a 404. So the component showed *"Screenshot no longer on the host"* as soon as the gate answered 401 — before the retry had even been made. A capture that was sitting on the host was reported as gone; only the retry's 404 was the true answer.

Reproduced live on `/monitoring/localize` (Playwright, `scripts/agent/probe_localize_frames.py`):

```
401  GET  /host/vpt-pi1/stream/capture4/captures/capture_003976814.jpg
401  GET  /host/vpt-mf1/stream/capture3/captures/capture_004773189.jpg
404  GET  /host/vpt-pi1/stream/capture4/captures/capture_003976814.jpg?_hs=1792684782816
404  GET  /host/vpt-mf1/stream/capture3/captures/capture_004773189.jpg?_hs=1792684782836
```

Two frames, four requests, four console errors. In this run both captures really were gone (the second request answered 404), so the text on screen was accidentally right — but it was right because of the 404, and the page had already given up on the first error.

The fix in BUG-0778's sibling `matchRunFrameSrc` (`frontend/src/utils/matchRunFrame.ts`) already reduced the stored value to its `stream/...` path so it goes through `buildHostImageUrl`; that part was right.

## Fix

The session is minted **before** the image is requested, so the only error left is a real one.

- `frontend/src/utils/buildUrlUtils.ts` — new `ensureHostSessionOnce(url)`: one mint **per host**, not one per image. The cookie is scoped to `/host/<name>/`, so a page showing twenty frames of one host needs one POST, not twenty. A successful mint is reused for four minutes (the cookie itself lives ten); a failed mint is never cached.
- `frontend/src/hooks/useHostSession.ts` — the initial mint goes through `ensureHostSessionOnce`; the keep-alive refresh (every four minutes) still calls `ensureHostSession` directly.
- `frontend/src/components/monitoring/MatchRunFrame.tsx` — the component calls `useHostSession(src, false)` and renders the `<img>` only once the session is there. A frame that is still loading shows a placeholder of the same footprint, so the row does not jump. `onError` now only ever fires for a file that is genuinely not there.

Result: one request per frame instead of two, no 401 in the console, and "Screenshot no longer on the host" means the file is gone.

## Verification

Measured live before the fix (see above): 4 requests for 2 frames, all four failing.

Regression tests: `tests/frontend/MatchRunFrame.test.tsx`
- "mints the host session before the image is requested" — the image is only in the DOM once the session exists;
- "does not ask for the file while the session is being minted" — no request before the cookie is there;
- "says the capture is gone only when the file itself is gone".

With the source reverted, 2 of the 3 fail; with the fix all 3 pass. `tsc --noEmit` is clean, and the suites that share `useHostSession` (`DevicePanel.vnc`, `useCrossServerControl`) still pass.


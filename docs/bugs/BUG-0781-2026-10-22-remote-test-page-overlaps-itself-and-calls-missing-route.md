# BUG-0781 — The Remote test page overlaps its own content with the mock stream box and the remote panel, and calls a route that does not exist

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0781                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding OPS-06, CHAOS-05, in `docs/tasks/QA-CHAOS-findings.md`, `docs/tasks/QA-OPS-findings.md`); reproduced against the live app.

- **Page / route:** /remote-test
- **Viewport / theme:** 1440 px, dark and light

Steps to reproduce:

1. Open `/remote-test`.
2. Look at the lower half of the page and the network panel.

**Expected:** The mock AV stream preview and the remote panel sit in the page flow with nothing covered or clipped.

**Actual:** The dashed "Mock AV Stream" box (bottom left) covers the "Test Android Mobile" heading and labels; the remote panel (bottom right) covers the "Use RecHostStreamModal Layout" card, and its bottom button row is clipped to `Scr1 | Scr | Scr | Scr`. The page also fires `GET /server/remote/getOrientation` which answers 400 ("No /server route matched") with no device selected.

Evidence:

- [ops-06-remote-test-overlap.png](../tasks/qa-evidence/ops/ops-06-remote-test-overlap.png)
- [desktop-dark-remote-test.jpg](../tasks/qa-evidence/chaos/desktop-dark-remote-test.jpg)

## Root cause

Three separate things, all on the same page.

**1. The mock AV stream box was pinned to the viewport.** `frontend/src/pages/RemoteTestPage.tsx` — the dashed "Mock AV Stream" box was `position: 'fixed'` with `bottom: 20, left: 20, zIndex: 1000`, inside a `position: 'relative'` test area that it therefore ignored. A fixed box does not move with the page: whatever content happened to be at the bottom-left of the viewport sat under it. That is why the sweep saw it cover the "Test Android Mobile" heading and the labels — the page was scrolled there.

**2. The remote panel was pinned to the viewport too.** `RemotePanel` floats by design (`position: 'fixed'`, `bottom`/`right` from the panel layout) — that is right on the Device pages, where it is meant to float over the stream. On this test page it was rendered the same way, so it sat over the page's own cards ("Use RecHostStreamModal Layout") and its bottom button row hung off the viewport. `RemotePanel` already supports the contained mode (`useAbsolutePositioning` + `positionBottom`/`positionRight`/`positionLeft`), which is what the modal branch of this page uses; the standard branch did not.

**3. The page asked the server about a host the server has never heard of.** The remote panel renders `AndroidMobileRemote`, whose hook `useAndroidMobile` auto-detects the phone's orientation with `POST /server/remote/getOrientation`. On this page the "host" is the mock `Test Android Mobile`, which the server does not know, so the request could only ever answer 400. The route itself **does** exist (`backend_server/src/routes/server_remote_routes.py:74`, POST only — a GET falls through to the auto-proxy catch-all and produces the "No /server route matched" message the sweep quoted). The failure was the call, not the route:

```
POST 400 https://virtualpytest.angelstreet.io/server/remote/getOrientation?team_id=…
console: [@hook:useAndroidMobile] Orientation auto-detect failed: Error: Host "Test Android Mobile" not found
```

## Fix

- `frontend/src/pages/RemoteTestPage.tsx` — the mock AV stream box is `position: 'absolute'`, so it sits inside the test area and moves with the page; the `RemotePanel` is rendered with `useAbsolutePositioning` and `positionBottom`/`positionRight` so it is contained too. Neither covers the page's own cards any more.
- `frontend/src/hooks/controller/useAndroidMobile.ts` — the orientation auto-detect now checks that the host is one the server knows (read from the host registry through `HostDataContext`, without the provider's throwing wrapper) and skips the request otherwise. The remote panel of a mock host still renders; it just no longer asks the server a question that has no answer.

## Verification

Regression tests in `tests/frontend/RemoteTestPage.test.tsx`:
- "keeps the mock AV stream box in the page flow instead of pinning it to the viewport" — the box's computed `position` must not be `fixed`;
- "does not ask the server for the orientation of a host it has never heard of" — no `/server/remote/getOrientation` request leaves the page;
- the original render test still passes.

With the source reverted, 2 of the 3 fail; with the fix all 3 pass. `tsc --noEmit` is clean.

Measured live before the fix (`scripts/agent/probe_remote_test_layout.py`): the page fired `POST /server/remote/getOrientation` → 400, and the mock box and the remote panel were both viewport-fixed (the remote panel's button row sat at y=848 in a 900 px viewport, clipped by the viewport edge). After the deploy, the same probe shows the box and the panel inside the test area and no orientation request.


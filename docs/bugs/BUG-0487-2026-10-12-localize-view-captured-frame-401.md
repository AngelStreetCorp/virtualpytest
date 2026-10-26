# BUG-0487 — Localize "View captured frame" opened a 401 instead of the capture

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0477                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend (localize diagnostics dialog)                       |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Clicking **View captured frame** in the Localize diagnostics opened

```
https://virtualpytest.angelstreet.io/host/vpt-mf1/stream/capture3/captures/capture_002125228.jpg
401 Authorization Required
```

The capture itself exists and the same URL renders fine inside an `<img>` on the device page.

## Root cause

`/host/<name>/stream/...` is gated by the proxy's `auth_request`: the host answers
`host_session_denied()` unless the short-lived host-session cookie is present
(`backend_host/src/routes/host_stream_routes.py:268`, and the same gate the VNC and HLS
paths sit behind). Two different things mint that cookie:

- a player (HLS / VNC), and
- `installHostImageSession`, which listens for an `<img>` **error** event on a gated path and
  mints the cookie once, then retries the src.

The button was a plain anchor — `<Button href={frame_url} target="_blank">`. A top-level
navigation is not an `<img>`, so nothing ever observed the 401, nothing minted the cookie, and
the new tab loaded an unauthenticated request. The helper for exactly this case already existed
and was used elsewhere (`Navigation_NodeEditDialog.tsx:1043`):

```ts
export const openHostUrl = async (url: string): Promise<void> => {
  await ensureHostSession(url);
  window.open(url, '_blank');
};
```

## Fix

The button is now an `onClick` that calls `openHostUrl(result.frame_url)`, which mints the cookie
at the gated URL's own origin and only then opens the tab.

## Verification

- `tsc --noEmit` exit 0, `eslint` exit 0 on `Navigation_LocalizeButton.tsx`.
- The same component's step-2 thumbnail uses a plain `<img>`, so the existing
  `installHostImageSession` retry covers it without any new code.
- **Not verified in a browser**: no live Localize run was driven against a fingerprinted device,
  so the opened tab was not re-fetched after the fix. Worth one click to confirm on a host that is
  up.

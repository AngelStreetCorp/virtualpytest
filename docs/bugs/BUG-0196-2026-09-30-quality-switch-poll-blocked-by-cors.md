# BUG-0196 — Switching stream quality took ~30 s and could end on an error, even though the switch had worked

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                          |
|-----------|------------------------------------------------------------------------------------------------|
| ID        | BUG-0196                                                                                       |
| Reported  | 2026-09-30                                                                                     |
| Status    | Fixed (pending deploy)                                                                         |
| Severity  | Medium (every LOW / SD / HD switch in the stream modal waited out its timeouts; a spurious error, and a second FFmpeg restart) |
| Area      | `frontend/src/utils/buildUrlUtils.ts` (`getStreamMediaSequence`, `pollForFreshStream`)          |
| Fixed in  | Unreleased                                                                                     |
| Commit    | `459b0e1a8`                                                                                    |

---

## Symptom

In the device stream modal (seen on a Raspberry Pi host reached through its own domain, device
`stb4`), clicking LOW / SD / HD showed "Loading HD quality stream... Waiting for stable stream"
for about 30 s, and sometimes ended with "Stream failed to reload after switching to HD quality",
although `POST /server/system/setStreamQuality` had returned `200 {"success": true}` and the
stream had in fact restarted in the new quality within a few seconds.

The browser console showed every manifest poll failing:

```
Access to fetch at '.../stream/capture4/segments/output.m3u8?_t=...' has been blocked by CORS policy:
Request header field cache-control is not allowed by Access-Control-Allow-Headers in preflight response.
[@utils:buildUrlUtils] Manifest check failed for <host>-device4: TypeError: Failed to fetch
```

and `Starting manifest polling ... (baseline sequence: -1)`.

## Root cause

Both manifest fetches used to detect the restarted stream sent `Cache-Control` and `Pragma`
request headers. These are not CORS-safelisted, so the browser sends a preflight first, and the
host nginx answers it with `Access-Control-Allow-Headers: Content-Type, Range` only. Every fetch
was therefore rejected:

1. `getStreamMediaSequence` returned `-1`, so there was no pre-switch baseline.
2. All 15 polls of `pollForFreshStream` (1 s apart) failed, and the 15 s timeout fired.
3. The timeout handler in `useRecQualitySwitch` retried by POSTing `setStreamQuality` again —
   restarting FFmpeg a second time — and polled another 15 s.
4. That failed the same way and showed the error.

HLS.js itself was unaffected (it sends no custom headers), which is why the video came back
behind the overlay.

## Fix

The two fetches no longer send custom headers — `cache: 'no-store'` plus the `?_t=<timestamp>`
query already defeat caching — and the poll now goes through `fetchHostMedia` like the baseline
fetch. The overlay now clears as soon as the restarted manifest has 3 segments.

## Verification

Before: `curl -X OPTIONS <manifest> -H 'Origin: <frontend>' -H 'Access-Control-Request-Method: GET'
-H 'Access-Control-Request-Headers: cache-control,pragma'` returns
`access-control-allow-headers: Content-Type, Range`, confirming the rejected preflight.

After deploy: open the stream modal, switch LOW → HD; the console shows `Manifest received` from
the first polls and `✅ Fresh stream ready` within a few seconds, with no CORS error, no timeout
and no second `setStreamQuality` request.

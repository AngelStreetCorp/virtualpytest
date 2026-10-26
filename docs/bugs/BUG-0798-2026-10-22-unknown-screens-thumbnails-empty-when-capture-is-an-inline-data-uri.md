# BUG-0798 — Four of fourteen thumbnails on the Unknown screens page are empty boxes because an inline data: capture is signed as a storage path

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0798                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                       |
| Severity  | Medium                                                       |
| Area      | frontend / backend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding DEVELOPER-07, in `docs/tasks/QA-DEVELOPER-findings.md`); reproduced against the live app.

- **Page / route:** /configuration/interface/stb_tv/unknown
- **Viewport / theme:** 1440 px, dark and light

Steps to reproduce:

1. Open `/configuration/interface/stb_tv/unknown`.
2. Scroll the "Needs a name" table and look at the Screen column.

**Expected:** Every row shows its screenshot.

**Actual:** Four rows show an empty grey box with no error. The browser requests a URL whose path is the base64 payload (`/virtualpytest/data%3Aimage/jpeg%3Bbase64%2C/...`) and gets 404, 400 or 520. `POST /server/storage/signed-url` with a `data:` URI returns `success: true` and a signed URL for it. The finder's sweep of 19 image pages found no other page with broken images apart from the AI dataset page. The Proposed-name column is covered in the evidence screenshot because it holds customer-derived text.

Evidence:

- [developer-07-unknown-screens-empty-thumbnails.png](../tasks/qa-evidence/developer/developer-07-unknown-screens-empty-thumbnails.png)
- [developer-07b-unknown-screens-dark.png](../tasks/qa-evidence/developer/developer-07b-unknown-screens-dark.png)

## Root cause

`frontend/src/utils/infrastructure/cloudflareUtils.ts` — `normalizeStoragePath()` had no `data:`
branch (four other components already guard it, for example `useVerification.ts:101`). A capture
that arrived inline as `data:image/jpeg;base64,…` therefore looked like a relative path in the
bucket, and `getR2Url()` asked the server to sign it. The chain was
`ReferenceImagePreview.tsx` → `useR2Url.ts` → `getR2Url()` → `POST /server/storage/signed-url`.

`backend_server/src/routes/server_storage_routes.py` signed any string, so the answer was a signed
URL whose path was the base64 payload: the browser asked for
`/virtualpytest/data%3Aimage/jpeg%3Bbase64%2C/…` and got 404, 400 or 520 — an empty grey box
where the thumbnail should be, and no error anywhere.

## Fix

- `frontend/src/utils/infrastructure/cloudflareUtils.ts`: `normalizeStoragePath()` recognises a
  `data:` URI and returns it as the resolved URL, so the picture is used as it is and the server is
  never asked to sign it.
- `backend_server/src/routes/server_storage_routes.py`: `POST /server/storage/signed-url` answers
  400 for a `data:` URI ("A data: URI is the image itself — use it as it is, it cannot be signed"),
  and the batch route reports it in `failed` instead of signing the payload.

## Verification

- `tests/frontend/StorageDataUri.test.ts` (new): `getR2Url()` returns the data URI as it is and
  never calls the signing route.
- `tests/backend_server/test_storage_signed_urls.py` (new): a data URI is a 400 and nothing is
  signed, a real path is still signed, and a batch reports the data URI in `failed` while signing
  the rest.

In the browser: `/configuration/interface/stb_tv/unknown` shows the screenshot of every row in the
"Needs a name" table whose capture arrived inline as a `data:` URI — the four that were empty boxes
now render (measured in the browser: 4 of 4 data-URI thumbnails load, 320x180 each;
screenshot: `../tasks/qa-evidence/fix/bug-0798-unknown-screens-thumbnails.png`).

The rows whose capture is a stored path are signed by the server and served from the app's own host.
They cannot be seen from a worktree build, because the page then runs on another origin
(`http://127.0.0.1:5073`) and the browser blocks the cross-origin picture
(`net::ERR_BLOCKED_BY_RESPONSE.NotSameOrigin`) — the same block in a bare `<img>` on a blank page,
while `curl` of the very same URL answers `200 image/jpeg`. From the app's own origin
(`https://virtualpytest.angelstreet.io`) the same URL renders (`naturalWidth` 1280), which is what
the deployed app shows — and what the "before" screenshot shows for those rows.

On the deployed build (`main-2026.10.22-89628`) every one of the twelve thumbnails loads, the four
inline captures included
(`../tasks/qa-evidence/fix/deployed/deployed-bug-0798-unknown-screens-thumbnails.png`).

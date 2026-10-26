# BUG-0775 — The AI Dataset review page asks you to judge screenshots that never load, and shows no error

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0775                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                       |
| Severity  | High                                                       |
| Area      | frontend / infra                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding DEVELOPER-02, CHAOS-03, in `docs/tasks/QA-CHAOS-findings.md`, `docs/tasks/QA-DEVELOPER-findings.md`); reproduced against the live app.

- **Page / route:** /training-review
- **Viewport / theme:** 1440 px, dark and light

Steps to reproduce:

1. Open AI > AI Dataset (`/training-review`).
2. Wait for the first sample (about 12 s).
3. Look at the screenshot panel next to the question.

**Expected:** The device screenshot is shown next to "Yes, correct" / "No, fix it".

**Actual:** Every sample (header reads `0/176`) shows a 20 px broken-image glyph with the alt text "Screenshot 1" and no error text. The console says `net::ERR_BLOCKED_BY_ORB`. Fetching the presigned URL with curl returns `403 Forbidden`, `content-type: text/html`, from the nginx in front of the training bucket, although the signature is fresh (`X-Amz-Expires=3600`); Chromium blocks the HTML-for-a-JPEG response. A reviewer answers blind and quietly corrupts the reference answers.

Evidence:

- [developer-02-ai-dataset-broken-image.png](../tasks/qa-evidence/developer/developer-02-ai-dataset-broken-image.png)
- [desktop-dark-training-review.jpg](../tasks/qa-evidence/chaos/desktop-dark-training-review.jpg)

## Root cause

Two causes, one visible effect.

**1. The pictures are served from a host the browser cannot read.** The list route signed the
URL of every training image with `MINIO_TRAINING_PRESIGN_ENDPOINT`
(`https://<training-host>`) and handed that URL to the page. The nginx in front of
the training bucket (`/etc/nginx/sites-enabled/virtualpytest` on the proxy host) answers only the
egress IPs in its allow-list:

```
map $http_cf_connecting_ip $training_client_allowed {
    default 0;
    "" 1;
    "<operator-egress-ip>" 1; # operator egress
    "<lab-egress-ip>" 1;     # lab egress (vpt-pi Pis)
    "<operator-laptop-ip>" 1;# operator laptop
}
```

The lab and the codebox now leave through `<origin-ip>` (the proxmox IP), which is not on that
list, so every image URL answered `403` with a `text/html` body from nginx — and Chromium then
blocked the HTML-for-a-JPEG response as opaque (`net::ERR_BLOCKED_BY_ORB`). The signature was
fresh; the host was the problem. Reproduced read-only on 2026-10-22: `curl` of a live
`image_url` answers `403`, `content-type: text/html`, 153 bytes, from this host and from the lab
server alike.

**2. The page said nothing about it.**
`features/ai-dataset/frontend/TrainingReview.tsx:1216` — `onError` marked the image as loaded and
nothing else. The spinner was replaced by the broken-image glyph, `imageReady` turned true, the
answer buttons were enabled, and the reviewer judged a picture they could not see and wrote the
answer into the reference set.

## Fix

The app no longer depends on that host: the server reads the picture out of the training bucket
and serves it.

- `features/ai-dataset/backend_server/server_training_samples_routes.py`: new route
  `GET /server/training-samples/<sample_id>/image` (`require_user_auth`, `ai.training:view`,
  team-scoped). It reads the object key from the database — never from the request — fetches the
  object from the training storage over the LAN (`MINIO_TRAINING_ENDPOINT`) and returns the bytes
  with the stored content type. The list route now returns `image_path` (that route) instead of
  a signed public URL.
- `features/ai-dataset/frontend/hooks/useTrainingSampleImage.ts`: new hook. It fetches the picture
  through the app's own API (the caller's credentials travel with it), keeps the blobs in a small
  session cache and answers with the reason when the fetch fails.
- `features/ai-dataset/frontend/TrainingReview.tsx`: a picture that cannot be loaded shows an
  error with a **Retry** button instead of a broken-image glyph, and the answer buttons stay
  disabled — a sample whose screen is not on screen is never judged. Skip and back still work, so
  the reviewer is not stuck on it.

The nginx allow-list on the proxy host still has the stale IPs. That no longer blocks the review
page (the app fetches over the LAN), but the scripts that read the bucket from the lab with a
presigned URL (`scripts/ai_bench.py`, `features/ai-dataset/scripts/export_dataset.py`) still get
403: `<origin-ip>` has to be added to `training_client_allowed`. That change needs sudo on the
proxy host, so it is not part of this fix.

## Verification

- `tests/backend_server/test_ai_dataset.py`: the image route serves the bytes with the stored
  content type, refuses another team's sample (404), says when a sample has no screenshot (404),
  reports a storage failure (502) and needs the team and the permission (400 / 403).
- `tests/frontend/TrainingReview.test.tsx`: a screenshot that cannot be loaded shows the reason
  and no broken image, the answer button stays disabled and `y` saves nothing, and Skip stays
  available.
- `tests/backend_server/test_ai_dataset.py::test_list_points_at_the_image_route_and_proposes_labels`:
  the list hands out the app route instead of a signed public URL.
  Run: `python3 -m pytest tests/backend_server/test_ai_dataset.py -q` — 101 passed.

In the browser (worktree build against the live backend):

- A picture that cannot be loaded shows the reason and a **Retry** button instead of a broken glyph, and
  the answer buttons **Yes, correct (y)** / **No, fix it (n)** are greyed out while **Skip (j)** and
  **Back (k)** stay alive — the reviewer is not stuck, but nobody judges a picture they never saw.
  Screenshot: `../tasks/qa-evidence/fix/bug-0775-training-review-image-error.png`.
- The broken-image glyph of the "before" state is gone: with no screenshot to show at all the panel
  says so in words instead of drawing a broken picture
  (`../tasks/qa-evidence/fix/bug-0775-training-review-missing-image.png`).

The picture itself on screen needed the new server route, which ships with the same change as the
page. On the deployed build (`main-2026.10.22-89628`) the review page shows the device screenshot
of the first sample, with the answer buttons live — the reviewer now judges what is on screen
(`../tasks/qa-evidence/fix/deployed/deployed-bug-0775-training-review-screenshot.png`).

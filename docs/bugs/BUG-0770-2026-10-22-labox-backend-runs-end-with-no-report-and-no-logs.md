# BUG-0770 — Every run on the labox-backend host ends with no report and no logs, so the Results pages have nothing to open

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0770                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                       |
| Area      | backend / reports                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding TESTER-03, in `docs/tasks/QA-TESTER-findings.md`); reproduced against the live app.

- **Page / route:** /run/monitor, /test-results/*, GET /server/script-results/getVerificationReviewMarkdown/<id>
- **Viewport / theme:** 1440 px, dark and light

Steps to reproduce:

1. From the Run page, run any script on `labox-backend` (for example `web/youtube_video_check.py`).
2. Wait for it to finish.
3. Open Test > Monitor Tests, or the run's Report column, or call the verification-review endpoint for the run.

**Expected:** A report link and a logs link, as the same script produces on host-clone-1 and host-clone-2.

**Actual:** The row shows `No Report` / `No Logs`; the review pack says `report_url: n/a`, `logs_url: n/a`; the result row keeps `html_report_r2_url`, `logs_r2_url` and `html_report_r2_path` null although the run itself is rich. Over the last 400 runs: host-clone-1 326 of 328 with a report, host-clone-2 21 of 35, labox-mobile 10 of 10, **labox-backend 0 of 27** (ten different script types). It is host-specific, not script-specific. A second, separate gap: on host-clone-2 every failed `game_tetris` run (14 of 14) has no report while all 9 passed ones do. OPS pass 8 also saw a failed `av_check` on labox-backend with no report. CHAOS got a report and logs for a failed `av_check` on host-clone-1, which fits the host-specific reading.

Evidence:

- [tester-03-monitor-no-report-no-logs.png](../tasks/qa-evidence/tester/tester-03-monitor-no-report-no-logs.png)

## Root cause

**It is the host, and it is the storage credentials — not the report upload code, and not the Results page.**

The affected host carries storage credentials the storage server does not know (cause class: storage key rejected), so every upload it makes is refused.

The chain, read from the live machines (read-only):

1. The artifacts are written by the **host**: `backend_host/src/routes/host_script_routes.py` runs the script and `shared/src/lib/executors/script_executor.py` → `shared/src/lib/utils/report_generation_utils.py` → `shared/src/lib/utils/cloudflare_utils.py` upload the report, the logs, the metadata JSON, the script source and the mosaic to the object store. The server only records the URLs the host hands back.
2. The affected host's storage key differs from the one the working hosts use, and the storage server rejects it.
3. The storage server does not know that host's key, so a bucket listing with its own credentials fails with `InvalidAccessKeyId` (storage key rejected). The same call from a working host succeeds.

4. So **every** upload from that host fails, not only the report. The run's `metadata` block proves it: a run from that host carries `verification_review.report_url: ""`, `verification_review.logs_url: ""`, no `metadata_r2_url` and no `script_source`, while the same script on host-clone-1 carries all four. In the object store, the folder of a failed-host run does not exist at all, while a working host's run folder holds `report.html`.

5. The Results page is healthy: a host-clone-1 run opens its report from the same UI, and the row it reads carries the full presigned URL. The page simply has nothing to show for labox-backend because the row has no URL.

The script itself is fine on that host — 16 of the 34 labox-backend runs in the last 400 succeeded (`success: true`), including every `smoke_*` script. They are green runs with no report.

### Two further findings from the same diagnosis

**a) The host is also in the wrong storage mode.** It mints public-mode URLs and lacks the presign endpoint the rest of the platform uses, so fixing only the key pair is not enough (see `docs/technical/architecture/MINIO_PRIVATE_BUCKET_GUIDE.md`).

**b) The `game_tetris` rows without a report are a different defect.** Every one of the 18 such rows (16 on host-clone-2, 2 on host-clone-1) was **created and never completed**: `created_at` = `started_at` + 150 ms, `completed_at` = `started_at`, `success: false` from the insert default, `execution_time_ms: null`, no `verification_review` block, no report. They are not upload failures — the host never wrote a verdict, so the report tail never ran. The same script that *passed* on the same hosts has a full report and a review pack. This one is a separate bug (the run is killed before `finalize_execution_context`), not the labox-backend credential problem.

### Layout finding (2026-10-22, refines the root cause)

On labox-backend the `vpt-host` unit has no `EnvironmentFile`, so the service does **not** load `/opt/virtualpytest/.env`; `app.py` loads only the `.env` in its working directory, `/opt/virtualpytest/backend_host/src/.env`, and that file had no `MINIO_*` variables. The host therefore ran on the code defaults (default access key, no secret), which is what the storage server rejected (`InvalidAccessKeyId`). The credentials in the root `.env` were never used. host-clone-1 differs: its unit has `EnvironmentFile=-/opt/virtualpytest/.env`, so its root `.env` is the file that counts there. Also: the root `.env` of labox-backend carried `MINIO_PUBLIC_URL` (the public-mode switch), host-clone-1 does not.

## Fix

**Platform side (shipped in this branch): a failed upload is no longer silent.** Until now the storage error was printed on the host and thrown away, so the row said "no report" with no reason and the review pack said `report_url: n/a`. Now:

- `shared/src/lib/utils/report_generation_utils.py` — `generate_and_upload_script_report` keeps the reason in the returned dict (`error`) instead of dropping it.
- `shared/src/lib/executors/script_executor.py` — the verification review pack gains an `Artifact upload failed: <reason>` line, and the run metadata gains `artifact_upload_error` (also inside `verification_review`). A green run whose report never reached storage now says why instead of looking empty.
- `backend_server/src/routes/server_script_results_routes.py` — the pack the reader actually gets **when the upload failed** (the server's own fallback, because the host's pack could not be uploaded either) gains the same line, read from the run metadata. Without this, the host's pack said the reason but the pack the reader opens said only `report_url: n/a` — the silent failure was still silent on the one host where it matters. Found by the live run below, not by the unit tests.

**Host side (ops action on the shared host, not done here):** set the storage key pair on that host to the one the working hosts use, switch it to the presigned-URL mode, then restart the host service. The runbook is in `docs/technical/architecture/MINIO_PRIVATE_BUCKET_GUIDE.md`. It changes credentials and restarts a service on a shared host, so it is an owner/ops step.

**Host side (done 2026-10-22, owner-authorised, lease held):** on labox-backend the storage variables were written into `/opt/virtualpytest/backend_host/src/.env` (the file the service loads), copied from host-clone-1's root `.env` without printing them: `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`, `MINIO_PRESIGN_ENDPOINT`, `MINIO_TRAINING_ENDPOINT`, `MINIO_TRAINING_ACCESS_KEY`, `MINIO_TRAINING_SECRET_KEY`, `MINIO_TRAINING_BUCKET`, `TRAINING_DATA_ENABLED`. `MINIO_PUBLIC_URL` was not added (leaves public mode). Backup: `backend_host/src/.env.bak-20261022215007`. Then `systemctl restart vpt-host` only. No unit and no root `.env` was changed. Left: the root `.env` of labox-backend still holds the old `MINIO_*` values and `MINIO_PUBLIC_URL` (unused by the service; clean-up is an ops decision); the unit still has no `EnvironmentFile`.

**Still open:** the `game_tetris` runs that never finalize (finding **b** above) — the host dies before the report tail, so no verdict is ever written.

## Verification

The diagnosis was reproduced live, read-only, from the machines:

- `list_objects_v2` with labox-backend's own credentials → `InvalidAccessKeyId`; with host-clone-1's → OK.
- The run folder of a labox-backend run is absent in the object store; the same folder for a host-clone-1 run holds `report.html` (87 KiB).
- The affected host's storage key differs from the working hosts' (storage key rejected).
- 0 of 34 labox-backend runs in the last 400 have a report; 318 of 320 host-clone-1 runs do; 16 of the 34 labox-backend runs succeeded, so the script is not the problem.

The platform-side fix is covered by `tests/shared/test_script_executor_upload_error.py` (6 tests; 4 fail without the fix) and `tests/backend_server/test_verification_review_upload_error.py` (4 tests; 2 fail without the fix).

**Live check on the deployed build** (a real `av_check` run on `labox-backend`, leased, released afterwards):

- The run `2fa13107-3d01-46ac-87e7-6b5735ced9e6` has no report and no logs, and its metadata now carries
  `artifact_upload_error: "InvalidAccessKeyId: storage key rejected"` — only the error code and a fixed phrase are stored; the raw storage text (endpoints, paths) is never kept.
  — the host's own storage error, which used to be thrown away.
- The same code confirms the diagnosis: the credentials are wrong, not the report code.
- The review pack the reader opens for that run is the SERVER's fallback (the host's own pack could not be uploaded either), and it said only `report_url: n/a` / `logs_url: n/a` — the gap the third bullet above closes.

**Live check after the host fix:** run `fe224c3b-e11c-4615-af16-5d02c528b117` (`web/youtube_video_check.py`, labox-backend, device `host`, leased and released) now has `html_report_r2_url` and `logs_r2_url` set and no `artifact_upload_error`. The script verdict itself was `success: false` (script outcome, unrelated to storage).

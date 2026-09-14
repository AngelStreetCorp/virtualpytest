# BUG-0058 — CI "Backend Server Unit Tests" showed success with a 404 report

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0058                                                     |
| Reported  | 2026-09-07                                                   |
| Status    | Fixed (verified on CI run #294; server 404 wording pending deploy) |
| Severity  | Medium (green job with no evidence; report link 404)         |
| Area      | .github/workflows/regression.yml · tests/backend_server · features/cicd report route |
| Fixed in  | build 8713                                                   |
| Commit    | `ee4a5693d` `40037aa60`                                      |

---

## Symptom

Test → Report listed run #290 "backend-server-tests" as success, but its link
(`/server/cicd/report/290/backend-server-tests/`) answered:

```
{"error":"The requested URL was not found on the server. …"}
```

On the server `/opt/ci-reports/290/backend-server-tests/` existed and was empty. Same for
runs 285, 287 and 289. (First suspected to be the `/server/*` lockdown — that was BUG-0057; this
one is a real missing file.)

## Root cause

The job runs `pytest --timeout=30 --timeout-method=thread`. With the *thread* method,
pytest-timeout aborts the **whole pytest process** on the first overrun, so pytest-html never
writes `pytest-report/index.html`. The step swallows the exit code, "Save job result" always
wrote `"report":"backend-server-tests"`, and the DB row got a `report_url` — hence a green job
pointing at an empty directory. The test that overruns is
`TestQuickTestExecution::test_execute_runs_on_the_device_host`, which runs a real script on a
device host and legitimately polls for up to 240 s.

## Fix (`ee4a5693d`)

- `--timeout-method=signal`: an overrun fails that one test and the run continues, so the
  report is always written.
- `@pytest.mark.timeout(300)` on `TestQuickTestExecution` — its own budget.
- "Save job result" advertises `"report": null` unless `index.html` exists; the Reports page
  hides the link for `null`.
- The report route returns a JSON 404 saying the job finished without writing a report when
  the job directory exists but the file does not.

## Second cause: runner clone 164 could not upload at all (`40037aa60`)

Run #292 (after the first fix) still had no backend report: the job ran on `vpt-164-1` and its
"Save job result" step failed with `Permission denied` on every ssh/scp to the server — hidden
by `continue-on-error`. Runner VM 164 is a clone of 163 and still had a stale
`~/.ssh/ci_reports_key.pub` from Sep 3. When a `.pub` sits next to the private key, ssh offers
*that* public key (which the server accepts, it is authorized) but signs with the private key
written from the secret, so the signature check fails. Runner 163 has no `.pub`, derives the
public key from the private one, and works. Every job scheduled on 164 since Sep 3 lost its
report the same way (e.g. #290 api-smoke and e2e-smoke).

Fix: the stale `.pub` was moved aside on 164, and all nine "Configure CI Reports SSH Key" steps
now `rm -f ~/.ssh/ci_reports_key.pub` after writing the key; the backend job emits an
`::error::` annotation and advertises no report if the upload fails.

## Verification

Run **#294** (first run with both fixes): backend job on `vpt-163-3` wrote and uploaded
`index.html` (550 KB, 435 tests in 4m34s: 427 passed, 7 failed, 180 skipped, 1 unexpected
pass) and `jobs/backend-server-tests.json` says `"report":"backend-server-tests"` with
`status: failure` — a red job **with** its evidence, which is the point. The api-smoke job of
the same run ran on `vpt-164-2` and uploaded too, proving the stale-`.pub` fix. Run #292 was
the negative control: same tests, job on `vpt-164-1`, nothing on the server.

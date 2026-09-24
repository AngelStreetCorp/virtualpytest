# BUG-0068 — Playwright E2E reports printed the auto-sign token in stdout attachments

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0068                                                                    |
| Reported  | 2026-09-08                                                                  |
| Status    | Fixed                                                                       |
| Severity  | Medium (security) — the token grants a signed-in session; reports are served to anyone who can open the CI/CD Reports page |
| Area      | tests/e2e/playwright/specs/_navigate.js, tests/e2e/playwright/global-setup.js |
| Fixed in  | build 8887                                                                  |
| Commit    | this commit                                                                 |

---

> **Redacted for publication.** This report is published at `/docs/bugs` and ships in customer bundles. The reproduction steps, the credential values and the inventory of which file held which secret have been removed: they are an attack recipe, not an engineering record. The full account is in this repository's history and in the internal task notes.

## Symptom

Every e2e test's **Attachments → stdout** in the published Playwright report read

```
🔐 Auto-sign navigation enabled: https://virtualpytest.angelstreet.io/?auto_signed=<full token>
```

`global-setup.js` printed the same URL once per run.

## Root cause

The navigation helper logged the full URL it opened, and the URL carries the
`E2E_AUTO_SIGN_TOKEN` as a query parameter. Playwright attaches test stdout to the HTML
report, which CI uploads to `/opt/ci-reports/<run>/e2e-*/` and serves through
`/server/cicd/report/<run>/…`.

## Fix

Both log lines mask the parameter value (`auto_signed=***`). Reports published before this
- Remediation for reports generated before this fix is tracked in the internal task notes.
.env on .105, backend .env on .103, GitHub secret `E2E_AUTO_SIGN_TOKEN`) or prune the old
`e2e-*` report directories on .103.

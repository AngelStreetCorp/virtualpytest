# BUG-0496 — AI calls made by a host were attributed to origin 'api'

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0496                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                          |
| Area      | backend / AI usage                                |
| Fixed in  | Unreleased                                                   |
| Commit    | `feat/ai-usage-review-r1`                                    |

---

## Symptom

On the AI usage page, the localize second opinion, freeze triage and other host-side features showed origin `api` (external API caller), hiding who really made the call and polluting the external-API share.

## Root cause

A host calls the server with the shared service key; `ai_caller_binding` set origin `api` for every service-key request and only a header that carried its own `origin` could refine it. A host process has a `host_name` (from `HOST_NAME`) but no entry-point origin, so it stayed `api`.

## Fix

`backend_server/src/lib/ai_caller_binding.py`: a service-key request whose `X-VPT-Caller` names a host but no origin is `monitoring`. `api` is left for callers with no host. Test: `tests/backend_server/test_ai_caller_binding.py`. Rows written before the deploy keep `api`.

## Verification

After the deploy, group the page by Origin over the last hour: `text.decision.localize` rows from `vpt-pi1` show `monitoring`; `api` only lists real external callers.

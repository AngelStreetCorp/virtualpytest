# BUG-0714 — navigate_to_url used the edge's wait_time as its page-load timeout

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0714                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / web controller                                |
| Fixed in  | build 90145 |
| Commit    | see `git log -- tests/backend_host/test_web_goto_timeout.py` |

---

## Symptom

A web edge whose `navigate_to_url` action had a short `wait_time` (2 s) failed when the page needed longer to load
(one Italian run of the language-free web tree, BUG-0709). Any slow page made such an edge fail.

## Root cause

`PlaywrightWebController.execute_command('navigate_to_url')` took `params['wait_time'] or params['timeout']` as the Playwright
`page.goto` timeout. `wait_time` is the pause the executor sleeps AFTER the action, so a 2 s pause became a 2 s load limit.

## Fix

`resolve_goto_timeout()` in `backend_host/src/controllers/web/playwright.py`: the goto timeout comes from `page_load_timeout`
(or the legacy `timeout`), default 30 s (`VPT_WEB_GOTO_TIMEOUT_MS`), never below 15 s (`VPT_WEB_GOTO_TIMEOUT_MIN_MS`).
`wait_time` is no longer read.

## Verification

`tests/backend_host/test_web_goto_timeout.py`; after the host deploy, the 4-language validation of the web tree passes.

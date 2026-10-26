# BUG-0701 — Web click by text failed on a match without a box although a later match was clickable

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0701                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | backend_host web controller                                  |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

TASK-135 phase 2 round 2, Flutter web app: `click_element(text)` fell back to the DOM dump and failed with
"Element found but no coordinates available", twice, although a later match in the same dump had a usable box.
The agent lost a call each time (see the follow-up list in `docs/tasks/TASK-135-web-tree-build-model-benchmark.md`).

## Root cause

`PlaywrightWebController.find_element` always returned the best-scored dump match (`matches[0]`). On Flutter the `flt-semantics`
nodes can be off-screen or zero-size, so that match had an empty `position`, and `click_element` gave up on it.

## Fix

`backend_host/src/controllers/web/playwright.py`: `find_element` keeps only matches with a usable box (`_has_usable_box`: x, y and a
non-zero width and height) and returns the first of them. Only when no match has one does it fail, with
"Element found but no coordinates available (N match(es) ... have no usable bounding box)".

## Verification

`tests/backend_host/test_web_click_and_js.py::test_dump_click_skips_matches_without_a_box` and `::test_dump_click_errors_only_when_no_match_has_a_box`.

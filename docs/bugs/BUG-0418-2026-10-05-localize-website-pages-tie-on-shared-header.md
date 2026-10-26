# BUG-0418 — Localize returned every page of a website as a candidate

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0418                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / Localize (image_helpers) |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On a web interface (`sauce-demo` on host-clone-1) Localize on the home page answered six candidates: home at 100 % and login, cart, search, products and register at about 97 %. The popover read "Possibly one of:" with six nodes, although the page was plainly the home page. Pages with a heading (login, cart, ...) were resolved by their title.

## Root cause

A page is scored by its best region only. All pages of one website share the header and the sidebar, so the best region is a few bits for every page, and the candidate band (14 bits) kept all of them. The fallback that narrows ties by distance used the same single best region, so it ruled nothing out. Home has no heading for the title step to use.

## Fix

The dHash path now carries each candidate's second-best region distance, and the fallback narrowing ranks by the sum of the two best regions. On the measured page the live home was 4 bits (1 + 3) from the stored home and at least 20 from every other page. Candidates that the title already decided are untouched, and nav-path candidates (TV menus) carry no second distance, so they behave as before.

## Verification

- `python3 -m pytest tests/backend_host/test_localize_web_pages.py` fails without the change (three candidates) and passes with it.
- After deploy: Localize on the sauce-demo home page answers `home` alone.

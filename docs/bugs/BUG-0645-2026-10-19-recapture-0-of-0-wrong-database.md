# BUG-0645 — recapture.py reports "0 of 0" when the interface is not in the shell's database

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0645 |
| Reported  | 2026-10-19 |
| Status    | Fixed (pending deploy) |
| Severity  | Low |
| Area      | scripts / localize |
| Fixed in  | build 90145 |
| Commit    | TBD |

---

## Symptom

`scripts/localize/recapture.py --ui stb_tv … --only <node>` printed `stb_tv: saved 0 of 0` and did nothing.

## Root cause

Not the tree lookup: the script ran on a laptop whose `.env` points to another Supabase project. There the interface
does not exist (`userinterfaces` returns no row), the script fell through to empty `trees` / `rows` and ended with a
clean-looking "0 of 0". On vpt-pi1 the same lookup finds 1 interface, 26 trees and 98 nodes.

## Fix

`recapture.py` stops with exit 2 and says which database it looks at when the interface is not found, and names vpt-pi1
as the place to run it. LOCALIZE_AUDIT.md §4 says so too.

## Verification

Run it on a laptop for `stb_tv`: error message, exit 2. On vpt-pi1: lists the nodes.

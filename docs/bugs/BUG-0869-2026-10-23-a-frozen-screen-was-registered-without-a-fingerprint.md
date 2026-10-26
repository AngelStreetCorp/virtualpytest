# BUG-0869 — A frozen screen was registered without a fingerprint, so the row could never be finished

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0869                                                          |
| Reported  | 2026-10-23                                                        |
| Status    | Fixed (pending deploy)                                            |
| Severity  | High                                                             |
| Area      | backend_host (freeze incident manager) / shared (screen registry) |
| Fixed in  | build 90145 |
| Commit    | (the TASK-162 branch)                                             |

---

## Symptom

A recurring screen kept re-appearing in the coverage report as **named but not fingerprinted**, even
after the fingerprint work had shipped and been deployed.

The concrete case: `vpt-pi1/device3`, a screen that had been seen 12 times that day, named
`Full-screen poster` by the hourly `auto-classify` job, with `fingerprint = NULL`. The coverage
metric — "screens >10 seen, not live, missing a label or a fingerprint" — went from 5 back to 6,
because a **new** unfinished row appeared rather than an old one coming back.

## Root cause

**There is a second place where a screen row is created, and it never had the fingerprint.**

`register_screen()` is called from two places:

- the **Localize monitor** (`backend_host/scripts/monitor_localize.py`) — it computes the v6 blob on
  every sighting and passes it down. This one was fixed by BUG-0847.
- the **freeze incident manager** (`backend_host/scripts/incident_manager.py`) — when a device freezes
  and Localize never published a screen id for that frame, the freeze registers the frozen frame
  itself, so the screen can be named later. It passed **only the identity hashes**
  (`{dhash, region_center}`) and no v6 blob at all.

So a row born from a freeze was born with `fingerprint = NULL`, and — before BUG-0867's count-path
fix — nothing could ever put a fingerprint on it. The monitor's fix did not reach it: the monitor never
registered that row, so the monitor's sighting never matched it either.

**The second half: the count path dropped the fingerprint too.** `count_sighting_by_id()` is what the
freeze path uses when Localize *did* publish a screen id. It counted the sighting and updated the
row, but it did not carry the caller's v6 blob — so a row registered before fingerprints existed kept
`fingerprint = NULL` on that path too, however often the screen froze.

That is why the row in the symptom is a poster: a poster on a screen is a **freeze** — the picture does
not change — so it is exactly the kind of screen the freeze path registers, and exactly the kind that
came out without a fingerprint.

## Fix

- **The freeze path stores the fingerprint.** `incident_manager.py` computes the v6 blob for the frame
  it is registering (`compute_fingerprint(frame, ocr=False)`, the cheap subset the matcher reads, no
  tesseract pass) and hands it to `register_screen()`, which stores it with the row. A row born from a
  freeze is born fingerprinted.
- **The freeze path also fills the rows that exist.** `count_sighting_by_id()` takes the blob and, when
  the row it is counting has no fingerprint, fills it **through the single writer**
  (`link_screen_fingerprint`) — never over an existing one, never a direct write.

The "written once" rule is unchanged and now holds on every path: a name goes through
`name_screen_row`, a fingerprint goes through `link_screen_fingerprint`, and neither ever overwrites
the other.

## Verification

- `tests/backend_host/test_monitor_screen_fingerprint.py` — a new test drives the real freeze path with
  a real frame on disk and asserts that the blob reaches `register_screen`.
- `tests/shared/test_screen_registry.py` — two new tests: a sighting fills a missing fingerprint through
  the single writer, and a row that already has one is left exactly as it is.
- All three fail without the fix and pass with it (checked by reverting the fix and re-running).

## Prevention

- **Fix every call site, not the first one you find.** BUG-0847 fixed the monitor's registration call.
  The same function had a second caller — the freeze path — and it was missed, because the symptom
  (a row with no fingerprint) looked identical to the one that had just been fixed.
- **A value the caller already holds must not be dropped by a path.** The freeze path had the frame in
  hand; the v6 was computable from it; nothing about that path asked for a fingerprint, so it did not
  compute one.

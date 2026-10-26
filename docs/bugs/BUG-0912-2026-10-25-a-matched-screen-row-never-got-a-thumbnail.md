# BUG-0912 — A screen seen again never got a picture, so the AI could never name it

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0912                                                          |
| Reported  | 2026-10-25                                                        |
| Status    | Fixed                                                             |
| Severity  | Medium                                                            |
| Area      | shared (screen registry)                                          |
| Fixed in  | build 90145 |
| Related   | [TASK-159](../tasks/TASK-159-screen-registry-single-writer.md), [BUG-0908](BUG-0908-2026-10-25-screen-state-checks-named-game-frames-full-screen-poster.md) |

---

## Symptom

On 2026-10-25, 9 of the 10 registry rows seen 5 times or more and still unnamed had a host file path
(`/var/www/html/stream/...`) as their picture, e.g. `vpt-mf1/capture5` (seen 47 times) and two `vpt-pi1/device4` rows
(31 and 9). The file had rotated away long ago, so the hourly namer skipped them (`no_sample`) every hour, for ever.

## Root cause

Those rows were made by the writers TASK-159 removed, which stored the host path. The new writers hand a durable
data-URI thumbnail to `register_screen`, but when the frame matched an existing row, `_match_and_count` only raised
`seen_count` and dropped the thumbnail. Only a sighting by id (`count_sighting_by_id`, the freeze path with a Localize
screen id) and the monitor's known-screen bump stored one.

## Fix

`_match_and_count` takes the caller's `sample_image_path`. When it is a `data:image/` thumbnail and the matched row's
picture is not one, the row gets the thumbnail in the same update. An existing thumbnail is never replaced, and a host
path is never stored on a match.

## Tests

`tests/shared/test_screen_registry.py`: `test_a_matched_row_without_a_thumbnail_gets_the_new_one`,
`test_a_matched_row_keeps_its_thumbnail_and_never_takes_a_host_path`.

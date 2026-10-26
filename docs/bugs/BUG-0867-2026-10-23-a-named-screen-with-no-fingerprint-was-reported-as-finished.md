# BUG-0867 — A screen with a name but no fingerprint was reported as finished, and a fingerprint could never be written to an existing row

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0867                                                          |
| Reported  | 2026-10-23                                                        |
| Status    | Fixed (pending deploy)                                            |
| Severity  | High                                                             |
| Area      | backend_server (screen label worker) / shared (screen registry)   |
| Fixed in  | build 90145 |
| Commit    | (the TASK-162 branch)                                             |

---

## Symptom

Two faults with the same shape: **a row that had been seen a hundred times carried no fingerprint, and
nothing in the platform could ever give it one.**

The coverage report said such a row was "labelled" and counted it as done. The owner's goal is a screen
that is **labelled AND fingerprinted** — a name alone does not finish a screen. On the lab, 21 of the 31
recurring screens (seen more than 10 times, not live) had a real name and **no fingerprint**, and the
report did not see it as unfinished.

## Root cause

**1. The metric counted the wrong thing.** `metric = unknown_n + unlabelled` — the rows with no NAME.
A row with a name and no fingerprint landed in the "labelled" bucket and was reported as finished.

**2. The fingerprint could never be written to an existing row.** Two paths create or count a sighting:

- the **insert** path, `register_screen_row()` — takes a fingerprint, and the monitor passes the v6 blob
  it computes (BUG-0847). This one is fine.
- the **count** path, `_match_and_count()` — what every REPEAT sighting takes, because a screen the
  device already has is counted, not re-inserted. Its UPDATE carried `seen_count`, `last_seen` and
  `updated_at`, and **no fingerprint**. The monitor's v6 was computed on every sighting and thrown
  away here.

So a row registered before the fingerprint existed kept `fingerprint = NULL` **for ever**, however
often the screen was seen again. Measured 2026-10-23: all 21 unfinished rows had been seen within the
last 7 days. They are recurring screens; they simply carried no fingerprint, and nothing could put one
there.

**3. A fingerprint had no single writer.** A name goes through `name_screen_row()`: only a row whose
label is NULL or `unknown_N` can be (re)named, and a real name is never overwritten. A fingerprint had
no such rule and no such function — the worker's `store_fingerprint()` was a plain table UPDATE that
would have overwritten whatever was there.

## Fix

- **`link_screen_fingerprint(p_team_id, p_id, p_fingerprint, p_node_id)`** (migration `20261023b`): the
  single writer for a fingerprint. It fills only a row whose `fingerprint` IS NULL, it never touches
  the label, and it never deletes. "A fingerprint is written once" is now a database rule.
- **The count path fills it.** `register_screen()` hands the fingerprint it already holds to the row it
  just matched, through the single writer. A row that has one keeps it.
- **The worker fills the rows that are already there.** A new pass (`--fingerprints-only` to run it on
  its own) goes over the rows that have a real name and no fingerprint: first the navigation tree (the
  node's own v6, and the row is linked to that node), then the row's own picture.
- **The metric counts what the owner asked for**: every row that lacks a label OR a fingerprint.

### The backfilled blob keeps the row's own identity

Not a convenience — a measurement. On every row that HAS a fingerprint, the row's `dhash` **is** the
blob's `dhash` and the row's `region_center` **is** the blob's `regions.center` (distance 0, not
"close"). A backfill that wrote anything else would describe a screen the row is not. The picture only
adds what the identity cannot: the focused tile's crop and the focus signature. The thumbnail's
per-region hashes are NOT copied in — a region is a FRACTION of the frame, and a 320x180 thumbnail of a
portrait screen has a different aspect, so its "top" covers a different part of the screen.

### Low confidence is listed, not written

The picture must agree with the row's own identity, or the row goes to the review list. All 21 keep a
320x180 thumbnail in the registry, and that thumbnail's dHash is within the matcher's tolerance of the
row's own full-frame dHash for 26 of 27 rows measured (median distance 7). Dry run over the 21: 20
would be fingerprinted, 1 goes to a human (its thumbnail is 13 bits off, one bit outside the tolerance
of 12) — and that row is seen every few days, so the source fix fills it exactly the next time it
appears.

### And none of them is in the navigation tree

Measured, because it changes what "link it to its tree node" can mean: **none** of the 21 has a tree
node with the same label, and none matches a node by hash. They are screens the tree does not know — a
TV broadcast, a game's promo, a photo of a room, a blue screen. The tree path is still the right answer
when it happens; it is simply rare.

## Verification

- `tests/scripts/test_screen_label_worker.py` 42 pass (+5): the metric counts a named row with no
  fingerprint; the picker takes only named rows without one; the fingerprint goes through the single
  writer and that writer's SQL touches no label column; the blob carries the row's own identity; and a
  picture that disagrees with the row yields nothing.
- The migration is applied on the lab database and `link_screen_fingerprint` returns an integer.
- The dry run over the 21 rows: 20 would be fingerprinted, 1 to a human, 0 written.

## Prevention

- A metric must count what the goal says, not a proxy for it. "Labelled" was a proxy for "finished", and
  the proxy hid 21 rows.
- A fact about a row needs ONE writer with the same rules the other facts have: written once, never
  overwritten, never a rename, never a delete. Two of the three row facts had that (the name, and now
  the fingerprint); the third (the sighting count) is a counter, and it is allowed to grow.
- A value that a caller already holds and a path silently drops is a bug in the path. The monitor
  computed the v6 on every sighting for exactly one reason, and the repeat-sighting path threw it away.

# BUG-0209 — AI Dataset: freeze strips showed no frame chips, so no frame read "during" or "after freeze"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0209                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — the reviewer of a freeze strip has no frame times or phases to judge it by |
| Area      | `features/ai-dataset/frontend/reviewText.ts` (AI → AI Dataset review page) |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

On **AI → AI Dataset**, a freeze-strip sample (`av-fault`, `model_answer.evidence = 'strip'`)
shows its strip image and the question "frozen 52.7 s", but none of the per-frame chips
(`+0.0 s · during freeze`, `+52.8 s · after freeze`) under it. The hint "Look only at the
'during freeze' frames" then points at labels that are not on the page. This is true for every
strip row in the lab DB (60 rows on 2026-10-01). Found while checking the TASK-27 freeze-wording
change (`f6897e83f`) against the reviewer's own strip, lab sample `d1479274`
(`frames: [0.0, 26.4, 52.8]`, `duration_ms: 52728`).

## Root cause

Two shapes for the same field. `shared/src/lib/ai/freeze_strip.py` returns
`meta.frames = [{file, t_rel_s}, …]`, but the capture hook that records the sample
(`backend_host/scripts/incident_manager.py`, step 4g) stores only the times:
`'frames': [f['t_rel_s'] for f in meta['frames']]`. The page's `stripFrames()` read
`asRecord(f).t_rel_s` from each entry; a number is not a record, so every entry was dropped
and the chip list was empty. The unit tests built their fixture from the `{file, t_rel_s}` shape,
so they passed against data that never exists. The scoring prompt (`family_prompts.py`) already
read the stored numbers correctly.

## Fix

`stripFrames()` reads `model_answer.frames` as the stored list of seconds since the first
frame. The tests now use that stored shape, plus the stored row of sample `d1479274`, which must
read `+0.0 s · during`, `+26.4 s · during`, `+52.8 s · after freeze`. The three strip tests fail
on the old code and pass on the new one.

## Verification

- `vitest` on `features/ai-dataset/frontend/reviewText.test.ts`: 24/24 pass; on the previous
  `reviewText.ts` the three strip tests fail.
- After a frontend deploy: open AI → AI Dataset, family `av-fault`, on both servers
  (Awesomation and RPI1-server). Each strip shows one chip per frame, and sample `d1479274`
  shows its +52.8 s frame as *after freeze*.

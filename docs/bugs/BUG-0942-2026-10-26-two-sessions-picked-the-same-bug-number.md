# BUG-0942 — Two sessions could pick the same bug number and turn `main` red

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0942                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | CI / repository hygiene / docs                              |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/bug-id-collision-gate`                       |

---

## Symptom

Three times in one day (2026-10-26) two sessions picked the same free bug number while both were working,
and the collision reached `main`:

| Number | Files that claimed it | How it showed up |
|---|---|---|
| BUG-0923 | the Pokémon stall fixer's doc, the Virtual Scripts typecheck doc | `check_bug_ids.sh` failed on `main` |
| BUG-0925 | the Victory Road 1F doc, the runner fix doc | same |
| BUG-0933 | the Pokémon wall-door doc, the CI runner disk doc | same |

The check says it plainly:

```
ERROR: bug number used by more than one file:
  BUG-0933
    BUG-0933-2026-10-26-the-ci-runner-root-filled-up-and-the-docker-build-died.md
    BUG-0933-2026-10-26-the-pokemon-runner-aimed-at-a-door-the-game-draws-as-a-wall.md
  Renumber the one that has NOT shipped to the next free number.
```

Until somebody renamed a file, **every** agent in the repo was working against a `main` whose own checks
failed, and the one who noticed had to guess which of the two files was allowed to keep the number.

## Root cause

**The number check only ever looked at the working tree, so the collision was invisible until the merge.**

`scripts/docs/check_bug_ids.sh` is a tree check: it reads `docs/bugs/` as it is on disk and refuses a
number that two files claim. Each session, on its own, holds exactly one of the two files — the number is
free in its tree, so its own check passes and its push passes. The number is only used twice in the
**merged** tree, which is the first moment the check can see it — by then `main` is red and the fix is
someone else's renumber.

The hook that runs before every push
([.githooks/pre-push](../../../.githooks/pre-push)) had gates for content (the leak gate, the game-slug
gate, the auto-sign token gate) and for the changed files (the review gate), but nothing compared a number
the push *adds* with the numbers the branch it will be merged into already carries.

## Fix

A new gate, `scripts/docs/bug_id_gate.sh`, compares the two sides before the push:

- the numbers the push **adds** under `docs/bugs/` (`git diff --diff-filter=A`),
- the numbers the **target branch** already carries (`git ls-tree` on `origin/main`, fetched first, because
  a session that pushes straight to `main` can be ahead of the local copy of that ref).

A number on both sides refuses the push and names the file that already holds it, the file that wants it,
and the next free number to take:

```
bug_id_gate: refusing the push: BUG-0933 is already used on origin/main.
  already there: docs/bugs/BUG-0933-2026-10-26-the-ci-runner-root-filled-up-and-the-docker-build-died.md
  this push:     docs/bugs/BUG-0933-2026-01-01-collision-test.md
  Rename yours to the next free number (BUG-0934 or later), then:
    - put BUG-0934 in the ID row and the title of the file,
    - update the release note entry that cites it,
    - regenerate the index: python3 scripts/docs/build_bug_index.py
```

One push that adds the same number twice is refused as well. The gate is wired into the pre-push hook
next to the other gates, so it runs on every push from a clone that has the hook active.

Three exit codes, because a gate that cannot look is not a pass and must not refuse the push either:
`0` clean, `1` a collision (refuse), `3` the target could not be read (say so out loud, do not refuse).

Bypass, with a reason, like the other gates: `BUG_ID_GATE_SKIP=1 git push`.

## Verification

- `bash scripts/docs/bug_id_gate.sh --selftest` — 4 assertions: a free number passes, a number the target
  already carries is refused, one push that adds a number twice is refused, and an unreadable target
  reports "could not check" (3) instead of refusing.
- End to end on the real hook: a push that added a document numbered `BUG-0933` while `origin/main` carried
  `BUG-0933` was refused with the message above, and the hook exited **1**.
- The renumber that this branch carries (the CI runner disk doc, BUG-0933 → BUG-0934) is itself the first
  collision resolved by the rule the gate now enforces: the file that reached `main` first keeps the number.

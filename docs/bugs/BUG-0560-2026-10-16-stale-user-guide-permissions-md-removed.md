---
bug_id: BUG-0560
title: docs/user-guide/permissions.md — stale model removed, replaced by agent/platform/ACCESS_MODEL.md
summary: Old file described the pre-tenant / pre-project / pre-role-ceiling model. Replaced by the new unified ACCESS_MODEL.md which audits each layer's implementation status. Links in user-guide/README.md, sharing-reports.md, grafana-alerting.md updated.
tags: [docs, bug, permissions, access-model]
keywords: [permissions, user guide, access model, tenant, team, user, role, workspace, project, ai budget, ACCESS_MODEL, stale, remove, replace, audit]
created: 2026-10-16
---

# BUG-0560

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0560                                                     |
| Reported  | 2026-10-16                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low (documentation drift)                                    |
| Area      | docs                                                         |
| Fixed in  | — (internal, docs-only removal)                              |
| Commit    | TBD                                                          |

## Symptom

`docs/user-guide/permissions.md` (8.6 KB) was the only document that explained "who can do
what" to end users. It described a 3-level model — account → profile (role) → team → workspace —
that predated **tenants** (TASK-23, 2026-09-23), **role ceilings** (TASK-31, 2026-09-29),
**projects** (TASK-65, 2026-10-15) and **AI budgets** (TASK-87, 2026-10-12). The doc:

- did not mention tenants at all (TASK-23 already shipped)
- called `teams.permissions` an additive grant when it is now a **ceiling** (post TASK-31)
- missed the project ACL entirely (TASK-65 G6 + G11)
- did not mention `ai_budgets` (TASK-87 phase 4)
- said "three roles" when there are five (admin / manager / developer / tester / viewer)

Worse: the file was linked from three other user-guide pages (`user-guide/README.md`,
`user-guide/sharing-reports.md`, `user-guide/grafana-alerting.md`) and from
`docs/agent/validation/CONTRACTS.md` (`§517`) and `docs/bugs/BUG-0154-…md` (`§92`). Operators
who read the user-guide followed a link into an outdated doc and could not find tenants,
projects or AI budgets.

## Root cause

Documentation drift. The doc was authored before TASK-23 (2026-09-23), TASK-31
(2026-09-29), TASK-65 G1–G11 (2026-10-06 → 2026-10-15) and TASK-87 (2026-10-12) shipped, and
was never updated to reflect the new layers. None of the task PRs added a check that the
permissions doc was kept current — a missing "doc freshness" gate.

## Fix

1. Added **`docs/agent/platform/ACCESS_MODEL.md`** (25 KB, frontmatter-indexed, regenerated
   by `scripts/gen_docs_index.py`). The doc:

   - lists all six access layers + the AI resource plane in a single table with their
     question, job, and source-of-truth doc;
   - shows the precedence (`user_effective → session_effective → project_effective`) and
     identifies the hard walls (tenant, team, viewer floor, admin);
   - audits every layer for DB / backend / frontend / auth coverage in a status table;
   - explains project scoping (how the tag joins to `executable_tags` + `device_flags.flags`);
   - explains AI routing (`usage → profile → endpoint → provider`) and quota rules
     (per-team, `mode warn|block`, fail-open on missing row);
   - lists **5 gaps** that still need development (BUG-0556 → BUG-0559);
   - lists the file map per layer and the depth docs at the end.

2. **Deleted `docs/user-guide/permissions.md`.**

3. Updated the three inbound links:

   - `docs/user-guide/README.md` — "Who can do what" entry now points at
     `../agent/platform/ACCESS_MODEL.md`.
   - `docs/user-guide/sharing-reports.md` — `§74` link updated.
   - `docs/user-guide/grafana-alerting.md` — `§423` link updated.
   - `docs/agent/validation/CONTRACTS.md` — `§517` "User-facing version:" updated to point
     at the new doc.

4. Regenerated `docs/agent/INDEX.md`, `docs/agent/INDEX.json`, and `docs/agent/platform/README.md`
   via `python3 scripts/gen_docs_index.py` so the new doc appears in the routing table.

## Verification

```
$ python3 scripts/gen_docs_index.py --check
index up to date

$ ls docs/agent/platform/ACCESS_MODEL.md
docs/agent/platform/ACCESS_MODEL.md

$ ls docs/user-guide/permissions.md
ls: docs/user-guide/permissions.md: No such file or directory

$ grep -rn "user-guide/permissions.md" docs README.md
(no matches)

$ grep -rn "ACCESS_MODEL.md" docs README.md
docs/INDEX.md:139: agent/ACCESS_MODEL.md — the one access-model doc for ...
docs/user-guide/README.md:33: ... [ACCESS_MODEL.md](../agent/platform/ACCESS_MODEL.md) ...
docs/user-guide/sharing-reports.md:74: ... [ACCESS_MODEL.md](../agent/platform/ACCESS_MODEL.md) ...
docs/user-guide/grafana-alerting.md:423: ... [ACCESS_MODEL.md](../agent/platform/ACCESS_MODEL.md) ...
docs/agent/validation/CONTRACTS.md:517: ... [ACCESS_MODEL.md](../platform/ACCESS_MODEL.md) ...
```

## Numbers

- Doc: **+25 KB** (`docs/agent/platform/ACCESS_MODEL.md`)
- Doc removed: **−8.6 KB** (`docs/user-guide/permissions.md`)
- Inbound links updated: **5** (3 user-guide + CONTRACTS + BUG-0154 addendum is itself
  self-contained)
- Index regenerated: **3 files** (`docs/agent/INDEX.md`, `docs/agent/INDEX.json`,
  `docs/agent/platform/README.md`)
---
bug_id: BUG-0559
title: AI budget is per-team only — no per-user / per-model / per-endpoint / per-project bucket
summary: `public.ai_budgets` PK is `team_id`. A team either has a cap or doesn't. Operators with multi-model setups (e.g. expensive Opus for `text.plan` only) cannot cap a single usage; a noisy single user cannot be isolated from their team.
tags: [bug, ai, quota, budget, ai_budgets, schema, gap]
keywords: [ai, budget, quota, ai_budgets, team, user, model, endpoint, bucket, per-model, per-user, cost, cap]
created: 2026-10-16
---

# BUG-0559

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0559                                                     |
| Reported  | 2026-10-16                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low (operational limit, no active bug)                       |
| Area      | db / backend / frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

## Symptom

`public.ai_budgets` (TASK-87 phase 4) is keyed `team_id UUID PRIMARY KEY`. The schema
supports **one budget per team** — a flat USD cap with `mode ∈ {warn, block}` and a
`warn_at` threshold.

```
$ psql -c '\d ai_budgets'
             Table "public.ai_budgets"
    Column      | Type | Nullable | Default
---------------+------+---------+---------
 team_id       | uuid | not null | *
 month_limit_usd | numeric(12,2) | not null |
 mode          | text | not null | 'warn'  -- 'warn' | 'block'
 warn_at       | numeric(3,2) | not null | 0.80
 updated_by    | text |          |
 updated_at    | timestamptz | not null | now()
```

The enforcement is also one-axis:

```
$ grep -rn "ai_budgets.blocked\|ai_budgets.current" backend_server/src shared/src
shared/src/lib/ai/budgets.py:43:def current(team_id, now) -> Optional[dict]:
shared/src/lib/ai/budgets.py:60:def blocked(team_id) -> bool:
backend_server/src/agent/core/manager.py: ai_budgets.blocked(self.user_identifier)
```

A user cannot have a *personal* monthly cap. A model (e.g. Opus on `text.plan`) cannot have a
*per-usage* cap. An endpoint cannot be capped separately. A project cannot be capped
separately.

## Why it matters

- A noisy single user can run up the bill for the whole team and only be discovered at the
  next team retrospective.
- A team that uses Opus for `text.plan` but cheap models elsewhere cannot isolate the Opus
  spend.
- A team that wants to ensure Atlas (`agent.atlas`) is always available cannot guarantee a
  floor on it.

## Fix

Extend the schema with a `bucket_type` column and a JSONB `bucket_ref` that holds the
discriminator + the reference. The gateway resolves the most specific bucket that applies
to the call (specificity order: usage > model > endpoint > user > project > team).

```sql
ALTER TABLE public.ai_budgets
    ADD COLUMN bucket_type TEXT NOT NULL DEFAULT 'team'
        CHECK (bucket_type IN ('team', 'user', 'model', 'endpoint', 'usage', 'project')),
    ADD COLUMN bucket_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD CONSTRAINT ai_budgets_bucket_pk PRIMARY KEY (bucket_type, COALESCE(bucket_ref->>'team_id', ...));
```

(The exact PK is a more involved migration because `bucket_ref` is JSONB. A safer pattern is
to keep `team_id` for the team bucket and add a separate `ai_budgets_specific` table for
finer buckets. The decision is product-level.)

**Resolution** in `shared/src/lib/ai/budgets.py::blocked(caller_context)`:

```
1. usage key bucket if present (e.g. text.plan: 50 USD/month, mode=block)
2. model bucket (e.g. claude-opus-4: 200 USD/month, mode=warn)
3. endpoint bucket
4. user bucket
5. project bucket
7. else team bucket (the existing path)

The MOST SPECIFIC non-null bucket wins (block beats warn; warn beats none).
Spend is summed across all buckets the call contributes to (denormalise on insert: each
ai_calls row stamps the bucket it counts against).
```

## Verification

After the migration:

- `ai_budgets` row with `bucket_type = 'user', bucket_ref = {user_id: alice}` caps Alice
  at 30 USD/month independently of the team's 500 USD/month.
- A row with `bucket_type = 'usage', bucket_ref = {usage_key: text.plan}` caps `text.plan` at
  100 USD/month even if the team hasn't hit its overall limit.
- Live: Alice's 31st dollar in a month refuses with the block message.

## Workaround today

None. Operators with multi-model setups accept a single coarse team cap.

## Related

- TASK-87 (`docs/tasks/TASK-87-ai-usage-analytics.md`) phase 4 — the schema that shipped
- `shared/src/lib/ai/budgets.py` — the resolver to extend
- `docs/agent/platform/ACCESS_MODEL.md` §7 G3 — surfaced during the access-model audit
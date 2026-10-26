# BUG-0612 — Endpoint, model, user, usage and project AI budgets could not be saved

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0612                                                     |
| Reported  | 2026-10-18                                                   |
| Status    | Fixed — migration applied on node1 2026-10-18                |
| Severity  | Medium                                                       |
| Area      | db / backend                                                 |
| Fixed in  | build 90145 |
| Commit    | `c87ac6037`                                                  |

---

## Symptom

Saving any budget other than a team budget (Settings → AI → Prices & budget, or `PUT /server/ai/budget` with
`bucket_type` = `endpoint`, `model`, `user`, `usage` or `project`) failed with
`null value in column "team_id" of relation "ai_budgets" violates not-null constraint`. Team budgets saved
normally. Seen on node1 while adding an endpoint budget for the `anthropic` endpoint.

## Root cause

Migration `20261016d_ai_budgets_finer_buckets.sql` (BUG-0559) re-keyed `ai_budgets` on
`(bucket_type, bucket_id)` and moved the owning team into the new `team_scope` column, but kept the original
`team_id UUID PRIMARY KEY` column, which stays NOT NULL after the primary key is dropped.
`ai_routing_db.upsert_bucket()` writes `team_scope` only. The unit tests use a fake Supabase, so nothing
caught the database constraint.

## Fix

- Migration `setup/db/migrations/20261018f_ai_budgets_drop_team_id.sql` (schema twin
  `setup/db/schema/071_ai_budgets_drop_team_id.sql`, rollback `20261018f_ai_budgets_drop_team_id_rollback.sql`):
  backfills `team_scope` from `team_id`, makes `team_scope` NOT NULL, drops `team_id`. Nothing reads `team_id`
  on budget rows any more.
- `tests/shared/test_ai_budgets_schema_contract.py` replays the ordered schema files and fails when
  `ai_budgets` has a required column that `upsert_bucket` does not write.

## Verification

After the migration: `\d ai_budgets` shows no `team_id`, `team_scope` NOT NULL; an endpoint bucket inserted
with the same columns `upsert_bucket` sends (no `team_id`) succeeds, and `GET /server/ai/usage/budget`
lists it.

Applied on node1 2026-10-18 (recorded in `applied_migrations`, method manual). Checked: `\d ai_budgets` has no
`team_id` and `team_scope` is NOT NULL; the server's own `upsert_bucket` saved, read back and deleted a `model`
bucket with no `team_id`. Customer databases need `20261018f` with their next deploy.

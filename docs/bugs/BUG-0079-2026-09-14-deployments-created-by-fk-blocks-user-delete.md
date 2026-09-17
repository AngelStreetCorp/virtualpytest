# BUG-0079 — `deployments.created_by` references `auth.users` with no `ON DELETE` action, so a user who created a deployment can never be deleted

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0079                                                     |
| Reported  | 2026-09-14                                                   |
| Status    | Fixed — migration applied on both environments; pending code deploy and customer DBs |
| Severity  | Low (latent — not reachable today)                           |
| Area      | database schema (`setup/db/schema/011_deployments.sql`)       |
| Fixed in  | build 8887                                                   |
| Commit    | `daa7efb31c`                                                 |

---

## Symptom

Deleting a user who has created a deployment fails with a foreign-key violation, and the account
can never be removed — offboarding is permanently blocked for that person because they once
scheduled a script.

**Latent, not live.** Nothing populates `deployments.created_by` today, so no user is currently
undeletable. Found while documenting the delete operation, by auditing what actually references
`auth.users`.

Combined with [BUG-0078](BUG-0078-2026-09-14-user-delete-reports-success-on-failure.md) the
failure was silent: the route discarded the failed result and reported `200 "deleted"`, so the FK
violation would have surfaced only as "we deleted them but they can still log in".

## Root cause

`setup/db/schema/011_deployments.sql` declared the column without an `ON DELETE` action:

```sql
created_by UUID REFERENCES auth.users(id)
```

Postgres defaults an omitted `ON DELETE` to `NO ACTION`, so a referencing row blocks the parent
delete. Confirmed against the live database — every other FK into `auth.users` cascades, and this
one alone does not:

```
 referencing_table          | column_name | delete_rule
---------------------------+-------------+-------------
 auth.identities           | user_id     | CASCADE
 auth.mfa_factors          | user_id     | CASCADE
 auth.oauth_authorizations | user_id     | CASCADE
 auth.oauth_consents       | user_id     | CASCADE
 auth.one_time_tokens      | user_id     | CASCADE
 auth.sessions             | user_id     | CASCADE
 public.profiles           | id          | CASCADE
 public.deployments        | created_by  | NO ACTION      <-- this one
```

## Fix

`ON DELETE SET NULL`, in both the base schema (for fresh installs) and a migration (for existing
databases): `setup/db/migrations/20260914_deployments_created_by_on_delete_set_null.sql`

```sql
ALTER TABLE public.deployments
    DROP CONSTRAINT IF EXISTS deployments_created_by_fkey;

ALTER TABLE public.deployments
    ADD CONSTRAINT deployments_created_by_fkey
    FOREIGN KEY (created_by) REFERENCES auth.users(id) ON DELETE SET NULL;
```

`SET NULL` rather than `CASCADE`: a deployment row is team history and must survive the departure
of whoever created it — the same rule already applied to `script_results` and campaign runs, where
deleting a user removes access but never the record of what was tested. Losing the author
reference is acceptable; losing the ability to revoke access is not.

## Verification

Safe to apply — the column is empty on every existing row, so the constraint swap rewrites no
data:

```sql
select count(*) as total_deployments,
       count(created_by) as with_created_by
from public.deployments;
```

```
 total_deployments | with_created_by
-------------------+-----------------
               289 |               0
```

A `grep` for writers of `created_by` on `deployments` in `backend_server/` and `shared/` returns
nothing, confirming the column is never populated by current code.

**Applied on 2026-09-14 to both environments we operate**, each showing the same before/after
(`NO ACTION` → `ALTER TABLE` ×2 → `SET NULL`) and no data disturbed:

| Environment | Database | Rows after | Constraint after |
|---|---|---|---|
| Main node | `192.168.x.102` | 289 | `... ON DELETE SET NULL` |
| proxmox3 / QualiAI | node3 `192.168.x.102` (VM 302) | 6 | `... ON DELETE SET NULL` |

Both run the same dockerised Supabase, so the same recipe applied — node3 needs the triple hop
(`proxmox` → `<node3-public-ip>` → `192.168.x.102`), with the `.sql` piped in as a file rather than
inlined, since quoting breaks at three levels.

**Still outstanding: customer databases.** `update_core.sh` deploys code but never runs migrations,
so every customer install needs this applied separately — flagged on the release-note entry. Verify
each with `delete_rule` for `public.deployments.created_by` reading `SET NULL`.

# BUG-0080 — A `group` that cannot be created is silently discarded: `_ensure_team` swallows every error into `None` and the call still returns `200`

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0080                                                     |
| Reported  | 2026-09-14                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | user provisioning (`shared/src/lib/database/users_db.py`)      |
| Fixed in  | Unreleased                                                   |
| Commit    | `7c1261d50d`                                                 |

---

## Symptom

Provisioning a user with a `group` returns `200` and `"team": null`. The group is dropped and the
caller is told the call succeeded, so an external system has no way to detect that team assignment
never happened.

This is the failure *mode* behind [BUG-0077](BUG-0077-2026-09-14-provisioning-group-dropped-team-insert-no-tenant-id.md).
That bug fixed the cause (a missing `tenant_id` on the insert); this one fixes the reason nobody
noticed it. The team insert had **never once worked** since the provisioning route was written, and
the API reported success every single time.

## Root cause

`_ensure_team` caught everything and returned `None`:

```python
def _ensure_team(admin, group: str) -> Optional[str]:
    try:
        ...
        return created.data[0]['id'] if created.data else None
    except Exception as e:
        print(f"[@db:users_db:_ensure_team] Error ensuring team '{group}': {e}")
        return None
```

`None` is indistinguishable from "there is no team", and the caller treated it as exactly that:

```python
team_id = _ensure_team(admin, group)
if team_id:                 # falsy on failure -> whole block skipped
    ...
    team_name = group       # never set, so the response says "team": null
```

So a database error, a constraint violation, an RLS change or a connectivity blip all produced a
`200` with the group quietly missing. The only trace was a `print` to the service journal.

A second, narrower instance sat immediately below it — the `team_members` insert swallowed *every*
exception in order to tolerate re-adding an existing member:

```python
except Exception:
    pass  # UNIQUE(team_id,user_id) — already a member
```

Only the uniqueness violation is the idempotent case; everything else was being hidden too.

## Fix

`shared/src/lib/database/users_db.py`.

`_ensure_team` now returns `str` and raises, which `_provision_upsert` already maps to a `500`
carrying the detail:

```python
    except Exception as e:
        # A concurrent provisioning call may have created the same team between the
        # SELECT and the INSERT; that is success, not failure — re-read it.
        if _is_unique_violation(e):
            again = admin.table('teams').select('id').eq('name', group).limit(1).execute()
            if again.data:
                return again.data[0]['id']
        raise RuntimeError(f"Could not ensure team '{group}': {e}") from e
```

The concurrent-create path is deliberate: two provisioning calls naming the same new group would
otherwise race, and losing that race is a success, not an error.

The `team_members` insert now ignores only `23505`, via a shared `_is_unique_violation` helper:

```python
        except Exception as e:
            if not _is_unique_violation(e):
                raise RuntimeError(f"Could not add {email} to team '{group}': {e}") from e
```

`UNIQUE (team_id, user_id)` is confirmed present on the table
(`team_members_team_id_user_id_key`), so that is a real idempotency case and not a guess.

### Deliberate consequence

The user and password are written *before* the group is applied, so a group failure now returns
`500` on a call whose user half already succeeded. That partial write is reported rather than
hidden, and the route is idempotent, so retrying converges. Documented in
`docs/integrations/user-provisioning.md` under "A `500` on a call that sent `group`".

## Verification

The uniqueness constraint relied on by the fix was confirmed against the live database:

```
team_members_team_id_user_id_key | u | UNIQUE (team_id, user_id)
```

`_ensure_team` has exactly one caller (`upsert_user`), so the signature change from
`Optional[str]` to `str` is fully contained — verified by grep across the repo.

Module compiles (`python3 -m py_compile`). **Not yet exercised against a deployed server** —
committed but not deployed. After `update_core.sh` reaches 192.168.x.103, confirm that a call with
a valid new `group` returns `200` with `"team": "<group>"`, that repeating it still returns `200`
(idempotent membership), and that the response no longer reports `"team": null` on success.

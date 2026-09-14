# BUG-0078 — Deleting a user reports `200 {"action":"deleted"}` even when the delete failed, and still removes the Grafana account

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0078                                                     |
| Reported  | 2026-09-14                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | user provisioning (`backend_server/src/routes/server_users_routes.py`) |
| Fixed in  | Unreleased                                                   |
| Commit    | `daa7efb31c`                                                 |

---

## Symptom

`DELETE /server/users/{email}` returns

```json
{"status": "ok", "action": "deleted", "email": "someone@example.com"}
```

with HTTP `200` **even when the user was not deleted**. The caller — typically an external
provisioning system offboarding someone — records a successful removal while the person still has
a working VirtualPyTest login.

When the call also carried `?grafana=true`, the outcome is worse than a no-op: the Grafana account
*is* deleted. The person loses dashboards but keeps platform access, and the inconsistency is
invisible to both sides.

Found while documenting the delete operation for the provisioning integration guide.

## Root cause

The email branch of `delete_user` discarded the result of the delete:

```python
if _is_email(user_id):
    existed = users_db.get_user_by_email(user_id) is not None
    users_db.delete_user_by_email(user_id)   # <- return value never inspected
    if _grafana_requested():
        ...                                   # runs regardless
    return jsonify({"status": "ok",
                    "action": "deleted" if existed else "absent",
                    "email": user_id}), 200
```

`action` was derived purely from whether the user existed *beforehand* — never from whether the
delete worked. And `users_db.delete_user` swallows every exception:

```python
    except Exception as e:
        print(f"[@db:users_db:delete_user] Error: {e}")
        return False
```

so any failure of `auth.admin.delete_user` — a Supabase blip, a foreign-key violation
([BUG-0079](BUG-0079-2026-09-14-deployments-created-by-fk-blocks-user-delete.md)), a missing
service-role client — produced `False`, which nothing read. Execution then fell through to the
Grafana mirror, which succeeded on its own.

The UUID branch had the same class of defect more mildly:

```python
success = users_db.delete_user(user_id)
if not success:
    return jsonify({"error": "User not found"}), 404
```

`delete_user` returns `False` both for "user absent" *and* for "delete failed", so a genuine
failure was reported to the operator as `404 User not found`.

## Fix

`backend_server/src/routes/server_users_routes.py` — inspect the result, and stop before Grafana:

```python
if not users_db.delete_user_by_email(user_id):
    logger.error(f"[delete_user] Platform delete failed for {user_id}")
    return jsonify({"status": "error", "error": "internal_error",
                    "detail": "Failed to delete the platform user"}), 500
```

`delete_user_by_email` returns `True` when the user is absent, so the idempotent "already gone"
path is unaffected and still reports `action: "absent"` with `200`. Only a real failure now
returns `500`, and the Grafana deletion is skipped so the two systems cannot be left inconsistent
in the dangerous direction.

The UUID branch resolves the user first, so `404` and `500` are no longer conflated:

```python
if not users_db.get_user(user_id):
    return jsonify({"error": "User not found"}), 404
if not users_db.delete_user(user_id):
    return jsonify({"error": "Failed to delete user"}), 500
```

## Verification

The delete lifecycle was exercised against the live server (192.168.x.103:5109) with a disposable
account while investigating; the success path and idempotency behave correctly and are unchanged
by this fix:

| Step | Result |
|------|--------|
| `DELETE /server/users/{email}?grafana=true` | `200 {"action":"deleted"}`; Grafana lookup → `404` |
| `DELETE` again | `200 {"action":"absent"}` |
| `GET /server/users/{email}` after | `200 {"exists":false}` |

The failure path was established by reading the code rather than by inducing a Supabase outage on
the production database. It is reachable whenever `auth.admin.delete_user` raises — most plausibly
a service-role/connectivity problem, or the FK in BUG-0079 once anything begins populating
`deployments.created_by`.

**Not yet re-run against a deployed server** — committed but not deployed. After
`update_core.sh` reaches 192.168.x.103, confirm the success and absent paths still return `200`
and that no regression was introduced in the normal offboarding flow.

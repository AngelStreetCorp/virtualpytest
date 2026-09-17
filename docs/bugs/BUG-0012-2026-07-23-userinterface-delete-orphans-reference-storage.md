# BUG-0012 — Deleting a userinterface orphans its reference folder in the bucket

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0012                                                     |
| Reported  | 2026-07-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend / storage / userinterface                           |
| Fixed in  | build 8414                                                   |
| Commit    | `80fc0453e`                                                 |

---

## Symptom

Deleting a userinterface (UI page → delete, or MCP `delete_userinterface`) removes it
from the app, but every reference screenshot it ever captured stays in the object store
(Cloudflare R2 / MinIO) forever. Over time the bucket accumulates orphaned
`reference-images/<userinterface_id>/…` and `navigation/<userinterface_name>/…` folders
(current refs, their greyscale/binary derivatives, and `history/` version snapshots) with
no UI or DB row pointing at them — dead weight that can never be reclaimed through the app.

## Root cause

The whole delete path was a pure DB-row delete plus a local cache invalidation, with no
storage call anywhere:

- `backend_server/src/routes/server_userinterface_routes.py:delete_userinterface_route`
  → `_invalidate_interfaces_cache` + `delete_userinterface` only.
- `shared/src/lib/database/userinterface_db.py:delete_userinterface` → single
  `supabase.table('userinterfaces').delete()`. Any FK cascade is Postgres-only and cannot
  touch bucket objects.

Reference images are stored under `reference-images/{userinterface_id}/…` (stable-id keyed
via `reference_storage_key`) and navigation screenshots under `navigation/{name}/…`, but
nothing deleted those prefixes. The storage util had no folder/prefix delete at all —
`CloudflareUtils.delete_file` removes a single key. Even single-reference
`delete_reference` deleted the DB row and left the object behind.

## Fix

- `shared/src/lib/utils/cloudflare_utils.py`: add `CloudflareUtils.delete_prefix(prefix)`
  (paginated `list_objects_v2` + batched `delete_objects`) and module-level
  `delete_userinterface_storage(userinterface_id, userinterface_name)` which deletes
  `reference-images/{id}/` (refs + greyscale/binary + `history/`) and `navigation/{name}/`.
- `backend_server/src/routes/server_userinterface_routes.py`: `delete_userinterface_route`
  captures the UI name **before** the DB delete (nav screenshots are name-keyed), then
  calls `delete_userinterface_storage` best-effort **after** a confirmed delete. Storage
  errors are logged but do not fail the delete — the DB stays the source of truth.
- `shared/src/lib/database/verifications_references_db.py`: `delete_reference` now calls
  `_delete_reference_storage(result.data)`, reclaiming the live object, its
  `_greyscale`/`_binary` derivatives and the `history/{name}/` folder.

## Verification

1. Capture a reference for a throwaway userinterface; confirm
   `reference-images/<id>/<name>.jpg` exists in the bucket.
2. Delete the userinterface. Server log prints
   `[@userinterface:delete] storage cleanup … removed N object(s)`.
3. Confirm `reference-images/<id>/` and `navigation/<name>/` are gone from the bucket.
4. Single reference: delete one reference; confirm its object + `_greyscale`/`_binary` +
   `history/<name>/` are removed while other references in the same UI survive.

# BUG-0460 — Mods preferences and widgets 500 on every page load when the mods tables were never migrated

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0460                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | db / backend                                                 |
| Fixed in  | build 90145 |
| Commit    | `5c05e00cc`                                                  |

---

## Symptom

On `<pi-server-host>`, every page load logged two failed requests for a signed-in user:

```
GET /server/mods/widgets?team_id=…&area=dashboard   → 500
GET /server/mods/preferences?team_id=…              → 500
[@mods] widget layouts not loaded; they stay in this browser
    Error: {'message': "Could not find the table 'public.user_widget_layouts' in the schema cache",
            'code': 'PGRST205', 'hint': "Perhaps you meant the table 'public.user_tenants'"}
[@mods] preferences not loaded; choices stay in this browser
    Error: {'message': "Could not find the table 'public.user_mod_preferences' in the schema cache",
            'code': 'PGRST205', 'hint': "Perhaps you meant the table 'public.verifications_references'"}
```

The app kept working (it fell back to browser storage), but two consequences were real:
the console filled with errors on every page load, and the **`PUT` paths failed too**, so
switching a mod on or off and reordering widgets were silently never persisted — the choice
never followed the user to another browser.

## Root cause

`features/mods/db/001_user_mod_preferences.sql` and `002_user_widget_layouts.sql` are
documented as *applied by hand on every database the release reaches* — no deploy script runs
them. On rpitest they had never been applied, so `public.user_mod_preferences` and
`public.user_widget_layouts` did not exist.

The fetch is **not** a sign that widgets are wrongly enabled: `ModsProvider.tsx:76-77` gates
the sync hooks on `installed.length > 0`, and `featureMods()` (`frontend/src/config/features.ts:162`)
returns the mods declared by every *enabled feature folder at build time* — not a runtime
"is a widget switched on" flag. So both calls fire once per page load on any deployment that
ships mods, which rpitest does. A shared login would not have shown this at all: `_person_id()`
returns `None` and both routes return early (`features/mods/backend_server/__init__.py:64-66`,
`:97-99`) without touching the database.

`mods_db.get_choices()` / `get_widget_layout()` let the PostgREST error propagate, and
`handle_route_exceptions` turns any exception into `jsonify({'error': …}), 500`.

## Fix

**1. Applied the two migrations** on the database behind `rpitest` — which turned out to be the
*shared* Supabase at `virtualpytest.angelstreet.io/supabase` (the `database` VM, `.102`), not a
per-rpitest database. Both files are `CREATE TABLE IF NOT EXISTS` and idempotent. PostgREST's
schema cache was reloaded with `NOTIFY pgrst, 'reload schema'`; its log shows relations going
**137 → 138 → 139**, i.e. both new tables picked up.

**2. Made the server degrade gracefully** (`features/mods/lib/mods_db.py`) so that any site
which forgets a migration no longer produces a 500. The frontend already has a supported way to
cope — both sync hooks treat a failed fetch as "stay in this browser" — so the server now
returns the same empty result (`{}` choices, `null` layout) and logs one line naming the
migration to apply. The `PUT` paths become no-ops that still answer 200, so a switch the user
just made no longer fails.

Only the **missing-table** case is swallowed (`PGRST205` / `42P01`, or the equivalent message).
`PGRST200`, timeouts and every other error still propagate, so a real bug or a real outage is
still reported as a 500.

## Verification

1. Applied both migrations with `ON_ERROR_STOP=1` — `CREATE TABLE`, policy and `GRANT` each
   succeeded, committed.
2. `information_schema` confirms both tables exist with `relrowsecurity = t`.
3. PostgREST log: `Schema cache loaded 137 Relations` → after the `NOTIFY`,
   `Schema cache loaded 138 Relations`, then `139`.
4. End-to-end through PostgREST with a short-lived `service_role` token minted from the local
   JWT secret: `GET /rest/v1/user_mod_preferences` → **HTTP 200 `[]`**, and the same for
   `user_widget_layouts`. `PGRST205` is gone.
5. `GET https://<pi-server-host>/server/mods/preferences?team_id=…` now returns
   **401** unauthenticated — rejected before the database is reached, rather than 500.
6. New offline tests `tests/backend_server/test_mods_db_missing_table.py` (11 cases) cover:
   the real `PGRST205` shape → `{}` / `None`; `PGRST200` and timeouts still raise; real rows
   still returned. All 21 mods tests pass; the full `tests/backend_server` run shows the same
   pre-existing environment-dependent fixture errors (13) on unmodified `main`.

## Follow-up worth considering

The migrations are still applied by hand on every environment, which is how this shipped
broken. A startup check that warns "the mods tables are missing on this database" would have
made it visible long before a user hit the console errors.
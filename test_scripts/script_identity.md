# Script and Campaign Identity Mapping

## Purpose

Decouple script/campaign names from business identifiers (for example `TC001`, `CP001`) and display labels.

You can rename test files/folders or campaign labels without losing your desired prefix, because prefix/display values are resolved from the identity store and stored in execution metadata.

## Where identity lives

**Source of truth: the `executable_identity` table** (`setup/db/schema/047_executable_identity.sql`),
edited from the **Test Cases page** — click the `TCnnn` chip on any row (rows with no prefix show a
faint `+TC` placeholder). Rows are keyed by `(team_id, kind, script_ref)`.

The legacy JSON files are a **read-only fallback**, kept for one release:

- `test_scripts/script_identity_map.json` — read by the server
- `frontend/public/data/script_identity_map.json` — read by the browser

Keeping these two in sync by hand is what BUG-0066 was about. Nothing needs to edit them any more;
import an existing map once with:

```bash
python3 scripts/import_script_identity_map.py --dry-run     # preview
python3 scripts/import_script_identity_map.py               # apply
```

### `script_ref`

The key is the canonical `script_ref` — the same namespace as `script_results.script_name`:

| kind | `script_ref` |
|---|---|
| disk script | path relative to `test_scripts`, without `.py` — `test_scripts/gw/superping.py` -> `gw/superping` |
| virtual script | its name — `superping` |
| testcase | the testcase name |

Resolution tries the exact ref first, then an **unambiguous basename** match. That second step is
why converting `gw/superping` into the virtual script `superping` keeps its `TC021`.

Legacy JSON structure (still accepted as a fallback, and what the importer reads):

```json
{
  "version": 1,
  "scripts": {
    "gw/superping": { "prefix": "TC021", "display_name": "Superping" }
  }
}
```

Campaign mapping (`test_scripts/campaign_identity_map.json`) is unchanged for now — the
`executable_identity` table reserves `kind = 'campaign'` for it, but nothing writes those rows yet.
Campaign lookup priority is `campaign_id` first, then campaign `name`.

## Runtime Behavior

Execution path:

1. Script executor normalizes the requested script into a canonical `script_ref`.
2. Campaign executor normalizes campaign identity into canonical `campaign_ref`.
3. Identity is resolved in priority order: `VPT_SCRIPT_PREFIX` / `VPT_SCRIPT_DISPLAY_NAME`
   env vars (what the server forwards) -> `executable_identity` rows for the team ->
   the legacy JSON file. Because the server always forwards what it resolved, a host
   needs no identity map of its own.
4. Values are written to metadata:
   - `script_results.metadata.script_identity`
   - `campaign_executions.metadata.campaign_identity`

Metadata example:

```json
{
  "device_id": "abc",
  "device_model": "xyz",
  "script_identity": {
    "script_ref": "gw/superping",
    "prefix": "TC001",
    "display_name": "Super Ping"
  }
}
```

## What This Does Not Change

- No script file rename is required.
- No `script_name`/`script_type` behavior is changed.
- No dashboard contract change is required now.
- Script identity uses existing `script_results.metadata` JSONB.
- Campaign identity uses `campaign_executions.metadata` JSONB (requires migration once).

## How To Change Prefix Later

Open **Test Cases**, click the prefix chip on the row, edit, Save. It applies to the next run.

Clearing both fields removes the identity entirely. A prefix already used by another script is
reported as a warning, not rejected — duplicates are allowed, so an existing map can always be
imported whole.

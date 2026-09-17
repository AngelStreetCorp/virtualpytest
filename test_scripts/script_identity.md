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

## The label — one definition

Everything that shows a script to a human renders the same string, with the same fallback chain:

```
[prefix] display_name  ->  display_name  ->  [prefix] script_name  ->  script_name
```

That chain lives in **one place per runtime**, and nothing should re-implement it:

| Runtime | Use |
|---|---|
| Python | `format_script_label(script_ref, prefix, display_name)` — `shared/src/lib/utils/script_identity_utils.py` |
| TypeScript | `formatScriptLabel(scriptName)` — `frontend/src/utils/executionUtils.tsx` |
| Grafana SQL | `COALESCE('[' \|\| prefix \|\| '] ' \|\| display_name, display_name, '[' \|\| prefix \|\| '] ' \|\| script_name, script_name)` over `metadata->'script_identity'` — as in `script-results.json` / `home-dashboard.json` |

A script with no identity row falls back to its own name, which is always a valid label.

Copies of this chain drifting apart is BUG-0099: one script ended up with four different names.

### In the API

`GET /server/script/list` returns the label so a caller never has to merge the map itself:

```json
{
  "scripts": ["gw/windows_networkassessmenttools"],
  "items": [{
    "script_ref":   "gw/windows_networkassessmenttools",
    "prefix":       "TC015",
    "display_name": "Windows Network Assessment",
    "label":        "[TC015] Windows Network Assessment"
  }]
}
```

- **`script_ref` is the identifier** — it is what you post back to `/server/script/execute`.
  Never send `label`.
- `label` is rendered server-side, so the browser, an external caller (dmacp, MCP) and the reports
  all show the identical string.
- `prefix` / `display_name` are `null` for an unmapped script and `label` is then the script name.
- `scripts` (bare names) is unchanged for existing callers. Prefer `items`.

The map is loaded once per request, so `items` costs no extra query. Identity writes
(`/server/script-identity/{set,clear,import}`) invalidate the script-list cache, so a rename on the
Test Cases page is visible immediately.

### In Grafana

A dashboard whose panels all query **one** `script_name` is that script's dashboard, so its **title
must be that script's label** — `[TC015] Windows Network Assessment`, not a hand-invented name.
Aggregate dashboards (several scripts, or none) keep free-text titles; their data labels already
build the label in SQL.

Check it, in the platform repo or any customer overlay:

```bash
python3 infra/monitoring/grafana/check_dashboard_titles.py          # exits 1 on drift
python3 infra/monitoring/grafana/check_dashboard_titles.py --fix    # rewrite the titles
```

It reads the repo's `script_identity_map.json`, so a name edited only in the Test Cases page reads
as drift until the map is re-exported.

## What This Does Not Change

- No script file rename is required.
- No `script_name`/`script_type` behavior is changed.
- No dashboard contract change is required — `metadata.script_identity` is unchanged;
  only per-script dashboard *titles* now follow the label (see above).
- Script identity uses existing `script_results.metadata` JSONB.
- Campaign identity uses `campaign_executions.metadata` JSONB (requires migration once).

## How To Change Prefix Later

Open **Test Cases**, click the prefix chip on the row, edit, Save. It applies to the next run.

Clearing both fields removes the identity entirely. A prefix already used by another script is
reported as a warning, not rejected — duplicates are allowed, so an existing map can always be
imported whole.

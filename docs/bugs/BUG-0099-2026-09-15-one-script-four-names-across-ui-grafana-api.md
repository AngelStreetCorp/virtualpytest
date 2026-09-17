# BUG-0099 — One script, four different names across the UI, Grafana and the API

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                  |
|-----------|----------------------------------------------------------------------------------------|
| ID        | BUG-0099                                                                                 |
| Reported  | 2026-09-15                                                                               |
| Status    | Fixed (pending deploy)                                                                   |
| Severity  | Medium                                                                                   |
| Area      | backend_server `/server/script/list` · shared `script_identity_utils` · Grafana dashboards |
| Fixed in  | build 9151                                                                               |
| Commit    | TBD                                                                                      |

---

## Symptom

A customer asked why the same test is called something different on every screen. For one
network-assessment script the four names in circulation were:

| Where | Name shown |
|---|---|
| The file / `script_results.script_name` | `windows_networkassessmenttools` |
| Run Tests, Test Cases, reports | `[TC015] Windows Network Assessment` |
| That script's Grafana dashboard | `Microsoft Teams Network Assessment` |
| `GET /server/script/list` | `gw/windows_networkassessmenttools` (no name at all) |

It was not one dashboard: **9 of 11** single-script dashboards on that install disagreed with the
identity map — `Gateway Information` vs `[TC001] Get System Information`, `DNS Lookup Time` vs
`[TC002] DNS Response Time`, `Email IMAP` vs `[TC048] Receive Email`, and so on.

## Root cause

Two independent gaps, both from the label having no single definition:

1. **Grafana dashboard titles are hand-typed free text** with nothing tying them to the identity
   map. The *generic* dashboards were already right — `script-results.json` and
   `home-dashboard.json` build the label in SQL from `metadata->'script_identity'` using the
   correct fallback chain — but a per-script dashboard's `title` is whatever the author typed when
   they created it, and it drifts the moment a display name is edited.

2. **`GET /server/script/list` returned bare strings only** (`{"scripts": ["gw/foo", ...]}`), so
   every consumer had to fetch `/server/script/identity-map` separately and re-implement the
   normalize + unambiguous-basename merge to get a name. The browser does exactly that in
   `frontend/src/utils/identityMapCache.ts`; an external API consumer could not do it at all and
   was left with the raw file name.

So the `[prefix] display_name → display_name → [prefix] name → name` chain existed in four
hand-written copies (TypeScript, two SQL expressions, report naming) and in zero shared places —
which is precisely how a fifth "copy" (a typed dashboard title) could say something else entirely
without anything noticing.

## Fix

- **One definition of the label.** New `format_script_label()` in
  `shared/src/lib/utils/script_identity_utils.py` renders the chain; new
  `lookup_identity_entry()` exposes the exact-then-basename lookup that was private inside
  `resolve_script_identity()`, which now calls it instead of repeating it.
- **`GET /server/script/list` carries the name.** Alongside the unchanged `scripts` array it now
  returns `items[]` with `script_ref` / `prefix` / `display_name` / `label`
  (`_build_script_items()` in `backend_server/src/routes/server_script_routes.py`). The identity
  map is loaded **once per request**, not per script, so there is no N+1. `script_ref` — never
  `label` — remains what callers post back to `/server/script/execute`. An unavailable identity map
  degrades each label to the script name rather than failing the list.
- **Stale labels on rename fixed.** `/server/script-identity/{set,clear,import}` now call
  `invalidate_script_list_cache()`; without it a rename on the Test Cases page would keep serving
  the old label for the cached response's TTL.
- **Dashboard titles made consistent** — all 10 single-script dashboards on the affected install
  retitled to their canonical label (`[TC015] Windows Network Assessment` etc.). `uid`s and file
  names are untouched, so existing links and bookmarks keep working.
- **Drift prevention.** `infra/monitoring/grafana/check_dashboard_titles.py` derives the rule
  generically: a dashboard whose SQL filters on exactly one `script_name` must be titled with that
  script's label. It skips aggregate dashboards (zero or several scripts) and ignores the `gw_info`
  context join. Exits 1 on drift so it can gate a push; `--fix` rewrites the titles.

## Verification

```bash
# Labels resolve, and an unmapped script falls back to its own name
python3 -c "from shared.src.lib.utils.script_identity_utils import format_script_label as f; \
  print(f('gw/x','TC015','Windows Network Assessment'), '|', f('gw/x',None,None))"
# -> [TC015] Windows Network Assessment | gw/x

# The list endpoint now answers with names
curl -s "$SERVER/server/script/list?team_id=$TEAM_ID" | jq '.items[0]'
# -> {"script_ref":"gw/...","prefix":"TC015","display_name":"...","label":"[TC015] ..."}

# Dashboard titles agree with the identity map (exit 0)
python3 infra/monitoring/grafana/check_dashboard_titles.py
```

Then on the deployed install: rename a script from the Test Cases page and reload Run Tests — the
new label appears immediately instead of after the list-cache TTL.

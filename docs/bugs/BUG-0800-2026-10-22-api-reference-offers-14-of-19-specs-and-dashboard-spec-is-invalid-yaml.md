# BUG-0800 — The API reference offers 14 of the 19 published specs, and the dashboard spec does not parse as YAML

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0800                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                       |
| Severity  | Medium                                                       |
| Area      | docs / frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding DEVELOPER-10, in `docs/tasks/QA-DEVELOPER-findings.md`); reproduced against the live app.

- **Page / route:** /docs/api and /docs/api/specs/*.yaml
- **Viewport / theme:** 1440 px, light

Steps to reproduce:

1. Open `/docs/api/interactive.html?spec=/docs/api/specs/server-dashboard.yaml`.
2. Open `/docs/api` and read the "Select API" dropdown.

**Expected:** The spec parses and the documented endpoints render; the dropdown lists the published categories.

**Actual:** The viewer shows "Parser error on line 105 / bad indentation of a mapping entry" and the misleading "does not specify a valid version field". The dropdown is a hard-coded list of 14; the five not offered are `server-additional-routes`, `host-backend-host-routes`, `server-log-review`, `server-masterchief` and `server-dashboard`. The last three document live routes and no other published contract covers them. `docs/INDEX.md` lists the same 14.

Evidence:

- [developer-10-rapidoc-parser-error.png](../tasks/qa-evidence/developer/developer-10-rapidoc-parser-error.png)

## Root cause

`docs/api/specs/server-dashboard.yaml:105` has an unquoted plain scalar containing `: `; the file is hand-maintained (not made by `scripts/generate_api_route_specs.py`). In YAML a plain scalar may not contain a colon followed by a space — the parser reads it as a mapping key and stops, so the whole file was unusable. The other 18 specs parse.

`frontend/src/components/docs/ApiDocsView.tsx:16-31` hard-codes the list of 14 specs, so a spec
that is added to `docs/api/specs/` is never offered. The three named categories missing from it
(`server-dashboard`, `server-log-review`, `server-masterchief`) document live routes — the
dashboard ones are called by the dashboard page itself — and no other published contract covers
them. The two bulk route dumps stay out of the dropdown on purpose: they are inventories of every
registered route, not categories.

Nothing parses the specs, so an unparseable one survived.

## Fix

- `docs/api/specs/server-dashboard.yaml`: the description is a folded block scalar (`>-`), so the
  colon inside it no longer ends the value. All 19 specs parse again.
- `scripts/generate_api_spec_manifest.py`: builds the list of specs the API reference offers from
  the files in `docs/api/specs/` (each spec labels itself in `info.title`; the two bulk dumps are
  left out) and writes `frontend/src/config/apiSpecs.ts`. `--check` fails when that file is stale.
- `frontend/src/components/docs/ApiDocsView.tsx`: the dropdown is that list — 17 specs instead of
  14 — so a new spec cannot be forgotten again.
- `tests/backend_server/test_api_specs.py`: every published spec parses as YAML and declares
  `openapi` and `info.title`; every spec that is not a bulk dump is offered; the list in the
  frontend is the generated one.
- `docs/INDEX.md`: the three missing specs are listed with the routes they document.

## Verification

- `tests/backend_server/test_api_specs.py` — 6 passed (`pytest tests/backend_server/test_api_specs.py`).
- `tests/frontend/ApiDocumentation.test.tsx` — the dropdown offers every published spec, including
  `SERVER - Dashboard`, `SERVER - Operator Log Review` and `SERVER - Masterchief Operations`
  (`scripts/run-vitest.sh ApiDocumentation` — 2 passed).
- `python3 scripts/generate_api_spec_manifest.py --check` — the list is up to date.

In the browser: `/docs/api` offers 17 specs, and
`/docs/api/interactive.html?spec=/docs/api/specs/server-dashboard.yaml` renders the two dashboard
endpoints instead of a parser error
(screenshots: `../tasks/qa-evidence/fix/bug-0800-api-reference-spec-list.png` — the picker with all
17 specs — and `../tasks/qa-evidence/fix/bug-0800-api-reference-specs.png`).

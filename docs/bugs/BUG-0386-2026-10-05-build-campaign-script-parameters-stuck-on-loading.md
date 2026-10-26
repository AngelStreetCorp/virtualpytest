# BUG-0386 — Build Campaign: a script's parameters stayed on "Loading parameters…" forever

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0386                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Closed                                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |

---

## Symptom

Run → Build Campaign: after adding a script to the run order and opening its row, the parameter
panel showed "Loading parameters…" and never changed, so a script's arguments could not be set
in a campaign. The browser made `GET /server/script/analyze/<script>.py`, which answered 400.

## Root cause

`loadScriptAnalysis` in `frontend/src/hooks/pages/useCampaign.ts` called
`GET /server/script/analyze/<name>`. The server only has `POST /server/script/analyze` with
`{script_name}` in the body (`backend_server/src/routes/server_script_routes.py`), as used by Run
Tests (`frontend/src/hooks/useRun.ts`). The hook also read `data.analysis.parameters`, while the
endpoint returns the analysis itself (`{success, parameters, script_name, has_parameters}`). On
any failure nothing was cached, so `ScriptSequenceBuilder` kept showing the loading text.

## Fix

- `useCampaign.ts`: `POST /server/script/analyze` with `{script_name}`, reading `parameters` from
  the response root.
- A failed analysis is cached with an `error` (new optional field on `ScriptAnalysis` in
  `frontend/src/types/pages/Campaign_Types.ts`), and `ScriptSequenceBuilder.tsx` shows
  "Could not load parameters: <reason>" instead of loading forever.

## Verification

- `cd frontend && ./node_modules/.bin/tsc --noEmit` passes.
- Live, before the fix: `GET /server/script/analyze/<name>` → 400, `POST /server/script/analyze`
  with `{"script_name": "<name>"}` → 200 with `parameters` at the top level.
- After deploy: Build Campaign → add a script → open its row: the parameter fields appear.

### Live check (2026-10-05, node1)

Run → Build Campaign, goto.py added and opened: the userinterface / variant / node / verify fields load; network shows `POST /server/script/analyze` → 200.

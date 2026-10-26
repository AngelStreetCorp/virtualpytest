# BUG-0796 — The API workspaces page prints a "Workspace ID" that, when pasted into the URL, answers "Workspace not found"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0796                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding DEVELOPER-04, in `docs/tasks/QA-DEVELOPER-findings.md`); reproduced against the live app.

- **Page / route:** /api/workspaces and /api/workspace/:workspaceId
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open `/api/workspaces`; the card shows `Workspace ID:` followed by a UUID.
2. Copy it and open `/api/workspace/<that UUID>`.

**Expected:** The printed id opens the workspace.

**Actual:** "Workspace not found" with a Back link. The list prints the Postman `workspace.workspaceId`; the View button and card click navigate with the internal slug `workspace.id` (for example `workspace-virtualpytest`), the only id the detail page resolves. Nothing on the page hints at the second id.

Evidence:

- [developer-04-api-workspace-not-found.png](../tasks/qa-evidence/developer/developer-04-api-workspace-not-found.png)

## Root cause

A workspace has two ids and the page mixed them up.

- `id` — the internal id (`workspace-virtualpytest`). The app's URL
  (`/api/workspace/<id>`) and every backend route (`/server/postman/workspaces/<id>/collections`,
  `?workspace_id=<id>`) resolve it.
- `workspaceId` — the id the **Postman** product knows the workspace by (a UUID).

`frontend/src/pages/UserApiWorkspaces.tsx` printed `workspace.workspaceId` under the label
"Workspace ID:", while the View button and the card click navigated with `workspace.id`
(`UserApiWorkspaces.tsx:251,295`) and the detail page resolved `w.id === workspaceId`
(`UserApiWorkspaceDetail.tsx:199`). Copying the printed id therefore opened nothing, and nothing on
the page hinted that a second id existed.

## Fix

- `frontend/src/pages/UserApiWorkspaces.tsx`: the line labelled "Workspace ID" now prints
  `workspace.id` — the id that opens the workspace. The Postman id is shown under it, labelled
  "Postman workspace ID", so the two are not confused.
- `frontend/src/pages/UserApiWorkspaceDetail.tsx`: the page also accepts the Postman workspace id,
  because that is the id Postman itself shows and the one a developer is likely to paste. The
  collections and the request definitions are then asked for with the id the backend resolves
  (`workspace.id`).

## Verification

- `tests/frontend/UserApiWorkspaces.test.tsx`: the id under "Workspace ID" is the one that opens
  the workspace, and the Postman id is labelled as the Postman one.
- `tests/frontend/UserApiWorkspaceDetail.test.tsx`: pasting the Postman workspace id opens the
  workspace and asks for its collections with the internal id.

In the browser: `/api/workspaces` prints `workspace-virtualpytest`; copying it into
`/api/workspace/workspace-virtualpytest` opens the workspace, and the Postman workspace id opens it
too (screenshot: `../tasks/qa-evidence/fix/bug-0796-api-workspaces-id.png`).

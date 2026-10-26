# BUG-0797 — The OpenRouter debug tool is dead: Execute always answers 400 because the backend route it calls no longer exists

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0797                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                       |
| Severity  | Medium                                                       |
| Area      | frontend / backend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding DEVELOPER-06, in `docs/tasks/QA-DEVELOPER-findings.md`); reproduced against the live app.

- **Page / route:** /configuration/openrouter
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open `/configuration/openrouter` (reachable by URL or bookmark only; it is no longer in the Settings menu).
2. Press Execute with the default model and prompt.
3. Read the Debug Logs.

**Expected:** The request is sent and the answer or model error is shown.

**Actual:** `POST /server/ai-tools/debug/openrouter` answers 400 ("No /server route matched ...", `unmatched_endpoint`). There is no code path that can succeed; the page looks like a working tool that is broken rather than a retired one. Also absent from the published API reference.

Evidence:

- [developer-06-openrouter-route-missing.png](../tasks/qa-evidence/developer/developer-06-openrouter-route-missing.png)

## Root cause

`frontend/src/pages/OpenRouterDebug.tsx:214` called the route; the module
`backend_server/src/routes/server_ai_tools_routes.py` was deleted (commit `8b4dce04b`, "kpi single
process and new ai") and its import in `routes/__init__.py:22` is commented out. The page was left
behind: it still rendered, still had a model list, a prompt box and an Execute button — and every
click ended in `400 {"error": "No /server route matched ...", "unmatched_endpoint"}`.

The page was also a leftover of the pre-unification architecture. It called
`shared/src/lib/utils/ai_utils.call_text_ai` directly with a model name, bypassing the routing,
the budget and the usage accounting that the AI stack has since. The capability itself is not
lost: Settings → AI → Endpoints has a **Test** button per endpoint
(`POST /server/ai/endpoints/<id>/test`), which runs a completion on a chosen model and shows the
answer.

The page was reachable by URL only — it is in no menu since the unification.

## Fix

The page is retired and its address points at the tool that replaced it.

- `frontend/src/pages/OpenRouterDebug.tsx` deleted (428 lines of dead code).
- `frontend/src/components/common/AiSettingsRedirect.tsx`: the old address
  `/configuration/openrouter` now redirects to `/configuration/settings?tab=ai`, so a bookmark
  lands on the working endpoint test instead of on a tool that answers 400.
- `frontend/src/App.tsx`: the route uses that redirect (the same pattern the app already uses for
  `/match-runs`).

No backend route is restored: a debug call that bypasses the routing, the budget and the usage
counting has no place in the unified AI stack.

## Verification

- `tests/frontend/AiSettingsRedirect.test.tsx`: `/configuration/openrouter` lands on the AI tab of
  the settings.
- The old page's own test (`tests/frontend/OpenRouterDebug.test.tsx`) went with the page.

In the browser: `/configuration/openrouter` opens Settings on the AI tab, where an endpoint can be
tested against a model; there is no page left that answers 400
(screenshot: `../tasks/qa-evidence/fix/bug-0797-openrouter-redirect.png`).

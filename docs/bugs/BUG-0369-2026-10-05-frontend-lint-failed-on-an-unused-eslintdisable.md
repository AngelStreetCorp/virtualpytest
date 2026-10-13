# BUG-0369 — Frontend Lint failed on an unused eslint-disable directive

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                |
|-----------|--------------------------------------|
| ID        | BUG-0369                             |
| Reported  | 2026-10-05 (Regression Tests on main stayed red after BUG-0367) |
| Status    | Fixed (pending deploy)               |
| Severity  | Medium — a required CI check was red |
| Area      | Frontend (agent chat page)                               |
| Fixed in  | Unreleased                           |
| Commit    | this commit                          |

---

## Symptom

Job `Frontend Lint` failed: `src/pages/AgentChat.tsx 423:67 Unused eslint-disable directive (no problems were reported from 'react-hooks/exhaustive-deps')`. The lint runs with `--report-unused-disable-directives --max-warnings 0`.

## Root cause

The server-picker effect added for BUG-0313 carried `// eslint-disable-line react-hooks/exhaustive-deps`, but its dependency list raises no warning, so the directive suppresses nothing.

## Fix

Removed the directive. No behaviour change.

## Verification

`cd frontend && npm run lint` exits 0.

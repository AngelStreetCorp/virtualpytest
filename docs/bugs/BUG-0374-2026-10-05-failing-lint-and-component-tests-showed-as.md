# BUG-0374 — Failing lint and component tests showed as green jobs on GitHub

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0374 |
| Reported  | 2026-10-05 (daily CI report and coordinator) |
| Status    | Fixed (pending deploy) |
| Severity  | Medium — real failures hidden from GitHub |
| Area      | CI / regression workflow |
| Fixed in  | Unreleased |
| Commit    | this commit |

---

## Symptom

The daily CI check reported platform rows in `cicd.ci_jobs` as `failure` for runs that GitHub showed as passing (#1750 lint, #1748 frontend-component-tests and api-routes).

## Root cause

The lint and component-test steps are `continue-on-error: true` so the report and the `ci_jobs` row are always written, and nothing afterwards failed the job (typecheck had such a gate, lint and component tests did not). The failures were real: `AgentChat.tsx` had an unused eslint-disable directive (BUG-0369), and three component tests (RunTests, Models, Workspaces) had been broken since the pages changed (RunTests needs an auth context since BUG-0186, Models gained `supportedModels`, Workspaces always lists the built-in All row since BUG-0292). The e2e and api-routes rows of #1748 were environment failures of the same run (Playwright browser install exited 100 while the runner disk was full) and heal with BUG-0367.

## Later finding (same day)

Once the jobs could fail, the component tests showed 13 more failures from the gold-palette page restyle (`PageChrome`): page titles had become plain `<Typography>` paragraphs, so they were no longer headings for screen readers or for `getByRole('heading')` (a real accessibility regression), and two pages had changed their title, empty-state text or export (Agents, Coverage, AgentDashboard default export + `useProfile`). Titles are `component="h1"` again (PageTitle, PAGE_TITLE_SX users, Build Campaign, Run Tests, Monitor Tests, Test Reports, Analytics); the AgentDashboard, Coverage and TestReports tests follow the new pages, and the Interface page title is a heading again.

## Fix

Both jobs now end with a `Fail the job if ... failed` step (same pattern as typecheck), so GitHub and the platform agree. The three tests are repaired: the auth context hook is mocked in RunTests, `supportedModels: []` added to the Models hook mock, and the Workspaces test asserts the built-in row. e2e/api-routes keep `continue-on-error` (they depend on live services); only the two jobs whose failures were code defects are gated.

## Verification

Locally `npx vitest run --config ../tests/frontend/vitest.config.ts` passes every test and `npm run lint` exits 0. On the next run lint and component-test jobs show the same status in GitHub and in `cicd.ci_jobs`.

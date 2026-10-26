# BUG-0772 — Monitoring > System shows the Grafana login form inside the app instead of a dashboard, and the dashboard picker request answers 401

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0772                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | frontend / infra                                             |
| Fixed in  | build 90145 |
| Commit    | —                                                             |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding OPS-02, CHAOS-04, in `docs/tasks/QA-CHAOS-findings.md`, `docs/tasks/QA-OPS-findings.md`); reproduced against the live app.

- **Page / route:** /monitoring/system, /grafana-dashboard
- **Viewport / theme:** 1440 px, dark and light

Steps to reproduce:

1. Open Monitoring > System (or Plugins > Grafana).
2. Look at the large panel under the "Select Dashboard" picker.
3. Check the network panel.

**Expected:** The Grafana dashboard renders inside the app and the picker lists the dashboards the viewer may open.

**Actual:** The panel is Grafana's own "Welcome to Grafana" login form. `GET /grafana/api/search?type=dash-db&limit=5000` answers `401` with Grafana's own error body, and the iframe request is redirected to `/grafana/login`. The picker falls back to the full static list, so it offers dashboards that cannot open. An operator must open Grafana separately and log in a second time.

Evidence:

- [ops-02-grafana-login-in-iframe.png](../tasks/qa-evidence/ops/ops-02-grafana-login-in-iframe.png)
- [desktop-dark-grafana-dashboard.jpg](../tasks/qa-evidence/chaos/desktop-dark-grafana-dashboard.jpg)

## Root cause

`frontend/src/pages/GrafanaDashboard.tsx:17` uses the Grafana URL directly from the browser, and no nginx config (`infra/proxy/nginx/config/*.conf`, `location /grafana/`) injects credentials or an auth gate, so the embed can never be pre-authenticated.

Measured on the live deployment (2026-10-22):

| Request | Answer |
|---|---|
| `GET /grafana/api/search?type=dash-db&limit=5000` | **401** `{"message":"Unauthorized","messageId":"auth.unauthorized"}` |
| `GET /grafana/d/2a3b060a-…/script-results?orgId=1&…` | **302** → `/grafana/login?redirectTo=%2Fd%2F2a3b060a-…` |

The page fetched the search list **and then ignored the answer**: the 401 was caught by an empty `.catch(() => {})`, `visibleUids` stayed `null`, and the code fell back to the full static list `GRAFANA_DASHBOARDS`. The iframe was rendered unconditionally, so Grafana's own login form (the 302 target) is what the operator saw inside the app.

Why the session is missing at all: Grafana keeps its own session, the app's session is a Supabase one, and nothing between them bridges the two — the nginx `location /grafana/` proxy only forwards, and the platform's Grafana integration (`shared/src/lib/utils/grafana_admin.py`) manages Grafana *users* server-side, never a browser session. The live build points the page at the app's own origin (`VITE_GRAFANA_URL=https://virtualpytest.angelstreet.io/grafana`), so a sign-in in a new tab **does** leave the cookie the iframe needs — but the page neither said so nor waited for it.

## Fix

The app cannot pre-authenticate Grafana, and Grafana's own configuration and credentials are out of scope for this fix. What the app can do is stop showing a login form as if it were a dashboard, and stop offering dashboards that cannot open.

`frontend/src/pages/GrafanaDashboard.tsx` now asks Grafana first and renders one of four states:

| Grafana answers | The page shows |
|---|---|
| 200 + the dashboards this viewer may open | the picker and the embedded dashboard, as before |
| **401** | **"Grafana asks for a sign-in"** — what it means, an **"Open Grafana to sign in"** button (opens `/grafana/login` in a new tab) and a **"Check again"** button. No iframe, no picker. |
| no answer at all | "Grafana did not answer" + "Check again" |
| signed in, but no dashboard is openable | "No dashboard here" |

The "Check again" button re-runs the probe, so the operator signs in in the new tab, comes back, clicks it once, and the dashboards open inside the app — the cookie is first-party on the app's own origin, so the iframe picks it up.

The picker is now shown only when there is something true to pick: it lists the dashboards Grafana says this viewer may open, and it is hidden while Grafana asks for a sign-in (it used to offer the full static list of dashboards that could not open).

The page was not translated before this fix (`GrafanaDashboard.tsx` is not in `frontend/src/i18n/translated-files.txt`), so its new texts follow the page and stay English for now; TASK-53 translates the page as a whole.

## Verification

Real browser, live Grafana (`scripts/agent/grafana_panel.py`, a Playwright probe that reads the page):

| | live app before | worktree after |
|---|---|---|
| iframe on the page | **yes** (`/grafana/d/2a3b060a-…/script-results`, title "Script Results") | **no** |
| what the panel shows | **Grafana's "Welcome to Grafana" login form** | "Grafana asks for a sign-in" + "Open Grafana to sign in" + "Check again" |
| "Select Dashboard" picker | shown, full static list | **hidden** |

After the deploy (build main-2026.10.22-89636) the same live page answers the same way: **no iframe, no picker, the sign-in panel**.

Re-checked after the deploys that followed: the live page still answers the same way — **no iframe, no picker, the sign-in panel** (`scripts/agent/grafana_panel.py`).

Screenshots: [before (live)](../../tasks/qa-evidence/fix/bug-0772-before-live.png) · [after (worktree)](../../tasks/qa-evidence/fix/bug-0772-after-worktree.png) · [after (live, deployed)](../../tasks/qa-evidence/fix/bug-0772-after-live.png).

Tests: `tests/frontend/GrafanaDashboard.test.tsx` — 4 cases: a signed-in viewer gets the picker and the iframe; a 401 gets **no iframe and no picker** but the sign-in panel; an unreachable Grafana gets the "did not answer" panel; the picker lists only what Grafana answered. Against the pre-fix sources the two new cases fail (the old page embedded the iframe and the picker anyway).

Checks: `tsc --noEmit` 0 errors · eslint clean on the changed file · the four local style checks (`theme_colour_check`, `button_role_check`, `icon_check`, `status_check`) all ok · the Grafana suites 6/6 passing.

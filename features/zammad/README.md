# zammad

Support tickets through a **Zammad helpdesk** (TASK-96). A user files an incident from inside the app
(Settings → Open a ticket); the ticket arrives in Zammad with version, server, team, user and page
already filled in, and the user is the requester, so Zammad's email replies reach them. VirtualPyTest keeps
only a small team-scoped index (`support_tickets`) so pages can list a team's tickets.

Packaged like `gitlab`: one folder, optional, and a deployment that does not want it never gets it.

## Parts

| Part | What it holds |
|---|---|
| `lib/model.py` | the ticket model: types, severities, frequencies, family → category, the workflow statuses, the Zammad state ↔ status map, the reporter-facing status, family/category → Zammad group. The server validates against it; `frontend/ticketModel.ts` mirrors it |
| `lib/base.py`, `lib/zammad.py` | provider interface + the Zammad REST client (`create_ticket`, `get_ticket`, `list_articles`, `add_reply`, `set_status`, `close`, `whoami`). Tickets are created for `customer_id: "guess:<email>"` with the `vpt_*` attributes |
| `lib/setup_zammad.py` | re-runnable setup of the Zammad instance: the workflow states and the `vpt_*` ticket attributes (see "Zammad setup") |
| `lib/config.py` | the instance in `state_path('zammad_instances.json')`, outside the deploy tree; env fallback; the Enabled switch |
| `lib/support_tickets_db.py` | the `support_tickets` index; every query filters by `team_id` |
| `backend_server/__init__.py` | `/server/zammad/*` routes, `register(app)` |
| `db/001_support_tickets.sql`, `db/002_ticket_model.sql`, `db/003_priority_severity.sql` (+ `_rollback`) | the table, then the ticket model columns and workflow statuses; idempotent, 002 refuses a table that already holds rows. Feature-owned, so not deployed when the feature is off. **Nothing applies them**: the operator runs them in order on each database (001 is on the lab DB since 2026-10-14) |
| `frontend/routes.tsx` | nav items, `/integrations/zammad`, the app overlay and the fr/de catalogs |
| `frontend/ZammadPage.tsx` | the Plugins page: status dot (connection + config source in its tooltip), Opened / Closed / Total counts over Today / 7d / 30d / All with Team / User / Project filters, instance (gear) dialog, recent tickets, the "Open a ticket" button |
| `frontend/SupportTicketsToggle.tsx` | the "Support tickets (Zammad)" row in Settings → Features → Feature Toggles: the Enabled switch |
| `frontend/ReportIncidentDialog.tsx`, `ReportIncidentHost.tsx`, `reportIncident.ts` | the compact form, the host core mounts, and the store behind `useReportIncident().open({ family, category, targetId, targetLabel, ticketType?, severity?, title?, details?, attachments? })` |
| `frontend/ticketModel.ts`, `useTicketLabels.ts`, `useTicketTargets.ts` | the enums, every word for them (one `t()` place), and the Target lists per category (see "Targets") |
| `frontend/locales/{fr,de}.json` | the feature's own translations (merged at load, so they are bundled only with the feature) |

## Core hooks (the residue when the feature is off: none that names Zammad)

Generic slots in `frontend/src/config/features.ts`, inert without a feature using them:

- `nav[].onSelect` and `nav[].isVisible` - a nav row that runs an action instead of navigating, with a runtime gate
- `settingsToggles` - a row in Settings → Features → Feature Toggles (`Settings.tsx` renders each; the component returns one `<SettingRow>`)
- `appOverlays` - components mounted once under the app providers (`App.tsx`)
- `translations` - a feature's own fr/de catalogs (`i18n/index.ts` `registerCatalogLoader`; `scripts/i18n-check.mjs` reads them)

## Configuration

Either environment (no UI needed):

```
ZAMMAD_URL=https://support.example.com   # no trailing slash
ZAMMAD_API_TOKEN=…                       # an agent's API token (Zammad: Profile → Token Access)
ZAMMAD_PUBLIC_URL=https://support.example.com   # optional: the address a browser opens; defaults to ZAMMAD_URL
```

or the page's Settings form, which writes the same to `zammad_instances.json` and proves them with
`GET /api/v1/users/me` before saving (a failing test saves nothing). A field left empty in the file falls back
to the environment, so the Enabled switch can be stored without copying the token into a file. Nothing is
hardcoded: the public URL comes from config, never from the code.

Zammad needs the groups `Devices`, `Hosts & System`, `Scripts`, `Dashboards`, `Platform`. The family/category → group map is
`group_for()` in `lib/model.py`: Platform → Hosts & System (Device → Devices), Scripting → Scripts, Monitoring → Hosts & System,
Dashboards → Dashboards, AI → Platform.

## Ticket model

Type (incident, bug, request, question) × Priority (P0 High, P1 Medium, P2 Low; set by the reporter, required on every type,
P1 preselected; sent to Zammad's built-in priority: P0 → 3 high, P1 → 2 normal, P2 → 1 low) × Severity (blocker, major, minor;
only incident and bug carry one, and need it) × Family → Category → optional Target × Frequency (always, frequent, random, once; always required). `fixed_in_build` is set by support later. The dialog
shows Type, Priority, Severity, Frequency, each on one line, then Family / Category / Target. Workflow statuses: new, accepted, assigned, in_progress, need_info, fixed, delivered,
reopened, closed, duplicate, wont_fix. Closed in the counts = closed, duplicate, wont_fix. The requester sees
Open (new, accepted, assigned, reopened) · In progress (in_progress, fixed) · Waiting for you (need_info) ·
Delivered, please check (delivered) · Closed (closed, duplicate, wont_fix); the API sends it as `reporter_status`.

## Zammad setup

```bash
set -a; . .env; set +a            # ZAMMAD_URL + an admin's ZAMMAD_API_TOKEN
python3 -m features.zammad.lib.setup_zammad
```

Creates the custom ticket states (accepted, assigned, in progress, need info, fixed, delivered, reopened, duplicate, won't fix),
the Object Manager attributes `vpt_type`, `vpt_family`, `vpt_category`, `vpt_target`, `vpt_severity`, `vpt_frequency`,
`vpt_fixed_in_build` and runs the object manager migration. A second run changes nothing. `need info` is a *pending reminder*
state, which Zammad only accepts with a `pending_time`; `ZammadProvider.set_status()` sets one.

## Targets (the form's third dropdown)

From what the app already loads, no list endpoint was added: server, host, device and service come from the ServerManager host
data (`getAllHosts`: servers, hosts, their devices, and the `service_health` units the Status page shows); heatmap, timeline and
incident use the devices; script, virtual script and testcase from `/server/executable/list`; campaign from
`/server/campaigns/listExecutables`; Grafana from `frontend/src/utils/grafanaDashboards.ts` (the Grafana page's list); report from
the latest script results; agent from `/server/agents/overview`.

## Enable / disable

- **Runtime (per server):** the **Support tickets (Zammad)** switch in Settings → Features → Feature Toggles (admin only; the row
  does not exist when the feature is disabled at deploy level). Off hides
  "Open a ticket" and makes `POST /server/zammad/tickets` and `/reply` answer `409 support tickets are disabled`.
  Existing tickets stay listed. A server with no URL/token behaves as disabled.
- **Deploy level:** `DISABLED_FEATURES=zammad` (in `customer.conf`, or `--disabled-features` on `deploy_customer.sh`)
  - the folder is not deployed, the routes are not registered, nothing is bundled. Check:
  `VITE_DISABLED_FEATURES=zammad npx vite build` leaves no Zammad page, dialog or string in `dist/`
  (the only hit for "zammad" is the build variable itself).

## Permissions

Reads (status, health, tickets) and creating a ticket need a signed-in user with a real email and membership
of the team. Changing the config or the switch needs the `admin` role. No `plugins.zammad:*` permission was
added on purpose: the permission lists live in core (`types/auth.ts`, `server_permissions_routes.py`) and
naming the feature there would put it in a build that disabled it.

## Tests

```bash
python3 -m pytest tests/backend_server/test_zammad.py tests/backend_server/test_zammad_provider.py -q
# live create / reply / read / close against a real instance:
ZAMMAD_URL=https://… ZAMMAD_API_TOKEN=… python3 -m pytest tests/backend_server/test_zammad_provider.py -q
```

The page is in `ui.pages.spec.js` and in `docs/agent/validation/TESTING.md`.

## Still open

G6 context buttons (they call `useReportIncident().open({...})` from inside the feature, or a core caller needs a
generic slot), G7 thread view, G8 webhook, G9 other providers - see `docs/tasks/TASK-96-support-tickets-zammad.md`.

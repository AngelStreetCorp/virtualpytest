# Navbar Visibility

This page explains how the menu items a user sees are chosen. An admin can hide an item for the whole deployment, or for one workspace only.

<div data-technical>

Three layers control which navbar items a user sees. All three use the **full route path** as the visibility key — no aliases, no segment stripping, no drift.

> This page covers the workspace's `hidden_pages` filter. Its two siblings — `device_filter` and `script_filter`, which narrow the device list, the script browser and the run history — are in [workspace-scoping.md](workspace-scoping.md).

</div>

---

## Layers

<div data-technical>

| Layer | Scope | When applied | Who controls it |
|---|---|---|---|
| **Env** (`VITE_NAV_*` in `frontend/.env`) | Deployment-wide | Build-time (rebuild required) | Ops via SSH / Admin Settings |
| **Admin Settings** (`/configuration/settings` → Features → Navbar Visibility) | Deployment-wide | Writes to the same `.env`, still requires frontend rebuild | Admin UI |
| **Workspace** (`/workspaces` → Edit → Pages) | Per-workspace | Runtime — no rebuild | Any admin, via UI |

Env says "this deployment doesn't ship feature X". Workspace says "user group A shouldn't see feature X even though it's shipped".

</div>

- **The deployment setting** hides an item for everyone. Changing it needs a rebuild of the frontend.
- **The workspace setting** hides an item for one group of users. It takes effect straight away, with no rebuild.

---

## Key format (unified)

<div data-technical>

Everywhere — `.env`, Admin Settings, workspace `hidden_pages` — items are identified by their **full route path** exactly as defined on `NavigationItem.path` in `frontend/src/config/navItems.tsx`.

```
/integrations/jira
/monitoring/heatmap
/test-execution/run-tests
```

Adding a new navbar item: add it to `navItems.tsx` with a `path`. It is automatically visible in the admin table and the workspace Pages tab.

</div>

---

## Env variables

<div data-technical>

| Variable | Effect |
|---|---|
| `VITE_NAV_HIDDEN` | Not rendered at all |
| `VITE_NAV_DISABLED` | Rendered but greyed out, not clickable |
| `VITE_NAV_COMING_SOON` | Rendered greyed out with a **Soon** badge |

All three take a comma-separated list of **route paths**. Default (all unset) = nothing hidden at the env level.

```env
VITE_NAV_HIDDEN=/integrations/jira,/integrations/slack
VITE_NAV_DISABLED=/langfuse-dashboard
VITE_NAV_COMING_SOON=/configuration/cicd-reports,/configuration/code-deployment
```

</div>

---

## Precedence

<div data-technical>

For a given nav item, the final visibility is resolved in this order:

1. If the active workspace lists the path in `hidden_pages` → **hidden** (workspace always wins).
2. Else if the path is in `VITE_NAV_HIDDEN` → **hidden**.
3. Else if the path is in `VITE_NAV_COMING_SOON` → **coming-soon**.
4. Else if the path is in `VITE_NAV_DISABLED` → **disabled**.
5. Else **visible**.

</div>

- The workspace setting always wins. If a workspace hides an item, it stays hidden there, whatever the deployment says.
- Otherwise the deployment setting decides: hidden, coming soon, greyed out, or visible.

---

## Implementation files

<div data-technical>

| File | Role |
|---|---|
| `frontend/src/config/navItems.tsx` | Single source of truth — nav items, icons, sections, `ALL_NAV_ITEMS` |
| `frontend/src/config/featureFlags.ts` | Parses env vars, exports `getNavVisibility(path)` |
| `frontend/src/contexts/workspace/WorkspaceContext.tsx` | Exposes `isPathHidden(path)` for the active workspace |
| `frontend/src/components/common/Navigation_Dropdown.tsx` | Dropdown rendering — combines workspace + env checks |
| `frontend/src/components/common/Navigation_GroupedDropdown.tsx` | Grouped dropdown rendering — same combination |
| `frontend/src/components/common/Navigation_Bar.tsx` | Standalone buttons (Dashboard, Device, Interface) use `isPathHidden` |
| `frontend/src/pages/Settings.tsx` | Admin Settings > Features > Navbar Visibility table (writes paths to `VITE_NAV_HIDDEN`) |
| `frontend/src/pages/Workspaces.tsx` | Workspaces > Edit > Pages tab (writes paths to workspace `hidden_pages`) |
| `frontend/.env.example` | Template with the three env vars |

</div>

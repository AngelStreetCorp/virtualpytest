# Workspace Scoping (devices & scripts)

A workspace shows you only part of the fleet. You pick the devices and scripts you want to see, and everything else is hidden.

The workspace settings have three lists:

- **Devices:** which devices are visible
- **Scripts:** which scripts are visible
- **Hidden pages:** which menu items are hidden. See [nav-visibility.md](nav-visibility.md).

<div data-technical>

Three allow-lists on the workspace row:

| Field | Scopes | Documented in |
|---|---|---|
| `device_filter` | Which `host:device` targets are visible | this page |
| `script_filter` | Which scripts are visible | this page |
| `hidden_pages` | Which navbar items are visible | [nav-visibility.md](nav-visibility.md) |

</div>

> **Your team's device limits still apply.** A device is shown only if both your limits and the workspace allow it. The workspace hides devices. It does not give you access to them.

<div data-technical>

A user may also have a device limit from their team, role or own
profile. `GET /server/users/<user_id>/scope` returns it as `effective_devices` (`null` = every
device). Keep a device only when it is in `effective_devices` (when that is a list) **and** in the
active workspace's `device_filter` (when a workspace is active). The web app does this in
`WorkspaceContext.isDeviceAllowed`. Same caveat as below: it filters what is shown, it does not
authorize.

</div>

> **The server does not filter scripts for you.** The app fetches the workspace once and filters the lists itself. One request is the exception, covered in [Execution history](#execution-history-the-one-server-side-filter).

<div data-technical>

There is no "give me the filtered scripts" endpoint.
The list APIs return everything, exactly as they do without workspaces. The client fetches the workspace once and filters the responses itself. One endpoint is the exception — see [Execution history](#execution-history-the-one-server-side-filter).

</div>

> **This is a view filter, not a security rule.** Team separation is enforced on the server by `team_id` and row-level security.

<div data-technical>

This is scoping, not authorization. Team isolation is `team_id` + RLS on the server. Workspace filters shape what a user is *shown*. The workspace's `permissions` / `denied_permissions` fields are a separate mechanism — see `agent/platform/USER_PERMISSION.md` §5.

</div>

---

## Fail open

**If no workspace is active, nothing is hidden.** Everything is shown.

<div data-technical>

**No active workspace means no filtering at all.** Every predicate returns "allowed" when `activeWorkspace` is null (and `isPathHidden` returns `false`). Do not invert this to deny-by-default — anonymous users and users who belong to no workspace would see an empty app.

</div>

---

## The API picture

The steps to add scoping to a page, using the server API.

### 1. Fetch the workspaces

Signed-in users get their own workspaces. People who are not signed in get the public ones.

<div data-technical>

There are two ways to ask. Which one you use depends on whether someone is signed in. It does not depend on how the server is secured.

```
GET /server/workspaces/user/<user_id>     # you have a Supabase user id
GET /server/workspaces                    # no user (no JWT / no login)
```

The `/user/` form returns every workspace that user can reach, directly or through a team. The plain form returns all workspaces. Call one, once, at app start.

**No JWT? Use the plain form.** `/server/workspaces/user/` with an empty `user_id` does not match the Flask route `/user/<user_id>` — it falls through to the auto-proxy catch-all and returns a 404 reading `Endpoint /server/workspaces/user/ is handled by a dedicated blueprint, not auto-proxy`. That is a routing miss, not an auth failure.

The plain form is `@require_admin_role`, but that gate reads `request.user_role`, which the global guard in `auth_middleware.py` sets for credential-only callers too — **defaulting to `admin`**:

| Credential | Role granted | Passes `@require_admin_role` |
|---|---|---|
| `X-API-Key: <API_KEY>` | `service` | yes (`ADMIN_ROLES = ('admin', 'service')`) |
| `SERVER_OPEN_MODE=true`, browser, no credential | `SERVER_PUBLIC_ROLE` (default `admin`) | yes, unless lowered |
| `X-Server-Key: <SERVER_PUBLIC_KEY>` | `SERVER_PUBLIC_ROLE` (default `admin`) | yes, unless lowered |
| Nothing, and none of the above configured | — | no — 401 before the route runs |

So a no-JWT client reaches it fine. If the deployment sets `SERVER_PUBLIC_ROLE=tester` or `viewer`, the plain form starts returning 403 — that is the one case where a no-JWT client cannot list workspaces at all.

</div>

> **No sign-in?** Use the plain form. The form with an empty user id returns a 404, which is a routing mistake, not a sign-in problem.

The plain form needs an admin-level key. Without a sign-in, the server still lets you through, unless the deployment says otherwise.

A workspace looks like this:

```json
[
  {
    "id": "3f2a…",
    "name": "Broadcast QA",
    "device_filter": ["vpt-pi1:device1", "vpt-pi1:device2"],
    "script_filter": ["goto_home", "zap_channel"],
    "hidden_pages": ["/test-reports"],
    "is_public": false
  }
]
```

The user picks one, and the app remembers the choice in the browser. That one workspace object is the whole filter.

<div data-technical>

The user picks one; the chosen `id` is persisted in `localStorage` under `vpt_active_workspace`. That one object *is* the filter.

Anonymous users have no memberships to query, so the VPT frontend calls the plain form and then filters client-side to `is_public` (`usePublicWorkspaces`). That `is_public` narrowing is the frontend's own product choice, not a server restriction — the endpoint returns every workspace. A client that wants all of them can simply not filter.

</div>

### 2. Keep calling the normal list APIs

The normal list APIs stay the same. Nothing new to pass in.

| What you need | API | How to filter it |
|---|---|---|
| Devices | `GET /server/system/getAllHosts` | keep a device when `device_filter` contains `` `${host_name}:${device_id}` `` |
| Scripts & test cases | `GET /server/executable/list?team_id=…` | keep an item when `script_filter` contains its name — **scripts only** |
| Execution history | `GET /server/deployment/executions/recent` | pass the filters as query params (below) |

### 3. Filter in JS

Keep only the items whose names appear in the workspace's list.

<div data-technical>

Both filters check whether a name is in the workspace list.

```js
// once, at app start — the plain form when there is no signed-in user
const url = userId ? `/server/workspaces/user/${userId}` : '/server/workspaces';
const workspaces = await fetch(url).then(r => r.json());
const ws = workspaces.find(w => w.id === localStorage.getItem('vpt_active_workspace'));

// the normal script list — unchanged, returns everything
const { folders } = await fetch(`/server/executable/list?team_id=${teamId}`).then(r => r.json());

const allowed = folders.flatMap(f => f.items).filter((item) => {
  if (!ws) return true;                          // no workspace = show all
  if (item.type !== 'script') return true;       // test cases aren't script-filtered
  const bare = item.id.replace(/\.py$/, '');     // list returns "goto_home.py"
  return ws.script_filter.includes(bare) || ws.script_filter.includes(item.id);
});
```

Devices work the same way. Check each device name, then drop the hosts that have no devices left.

```js
const hosts = await fetch('/server/system/getAllHosts').then(r => r.json());

const visible = hosts
  .map((h) => ({
    ...h,
    devices: h.devices.filter(
      (d) => !ws || ws.device_filter.includes(`${h.host_name}:${d.device_id}`)
    ),
  }))
  .filter((h) => h.devices.length > 0);
```

</div>

### Execution history — the one server-side filter

The run history is filtered on the server, so a busy workspace next door cannot push your own runs off the list. Reload it whenever you switch workspace.

<div data-technical>

```
GET /server/deployment/executions/recent?device_filter=[…]&script_filter=[…]
```

Both params are JSON-encoded arrays, URL-encoded.

This one is server-side because the endpoint returns only the most recent rows **globally**. Fetch 20 and then filter, and a busy neighbouring workspace fills all 20 while your table comes back empty. The server applies the filter to the embedded `deployments` resource **before** the row limit, so each workspace gets its own most-recent rows.

```js
const qs = new URLSearchParams();
if (ws?.device_filter?.length) qs.set('device_filter', JSON.stringify(ws.device_filter));
if (ws?.script_filter?.length) qs.set('script_filter', JSON.stringify(ws.script_filter));

const history = await fetch(`/server/deployment/executions/recent?${qs}`, { cache: 'no-store' })
  .then(r => r.json());
```

Refetch whenever the active workspace changes — the rows on screen were filtered for the *previous* scope.

Server side (`backend_server/src/routes/server_deployment_routes.py`): device pairs become `or(and(host_name.eq.X,device_id.eq.Y), …)`; script names become `in.(…)` with an `ilike.*campaign*` leg so file-campaigns stay visible. When both filters are present the embedded-logic param is injected by hand, because postgrest-py has no `and_(reference_table=…)`:

```python
query.params = query.params.add(
    'deployments.and', f'(or({_device_inner()}),or({_script_inner()}))'
)
```

Values containing `,()"` are dropped rather than quoted — real host/device/script names never contain them.

</div>

---

## How the frontend wires it

The same API calls, wrapped in one React context. No page has to know when the workspace changed.

### One context, three checks

The workspace context gives every page three checks: is this device allowed, is this script allowed, and is this menu page hidden.

<div data-technical>

`WorkspaceProvider` owns the active id and exposes `isDeviceAllowed`, `isScriptAllowed`, `isPathHidden` — the same `includes()` checks, memoized. It needs `AuthProvider` above it, and it must wrap `RunExecutionsProvider`, which consumes it.

```ts
const isScriptAllowed = (scriptName: string): boolean => {
  if (!activeWorkspace) return true;
  const filter = activeWorkspace.script_filter ?? [];
  const bare = scriptName.endsWith('.py') ? scriptName.slice(0, -3) : scriptName;
  return filter.includes(scriptName) || filter.includes(bare) || filter.includes(`${bare}.py`);
};
```

</div>

### Devices are filtered at the hook, not the render

Devices you cannot see drop out of the run page's list and out of "select all". If you switch workspace, any hidden device you had selected is removed. A run cannot start on a device you cannot see.

<div data-technical>

`RunTests.tsx` never calls `isDeviceAllowed` for the target list. `useTargetSelection` wraps `useHostData` and re-exports a filtered `getDevicesFromHost` and `allHosts`, so `TargetPanel`, "select all" and the display-name lookup are all scoped from one place. Hosts left with zero allowed devices drop out.

The same hook prunes the current selection when the workspace changes, so a run can never be launched against a target the user can no longer see:

```ts
useEffect(() => {
  setSelectedDevices((prev) => {
    let changed = false;
    const next = new Map<string, string>();
    prev.forEach((ui, key) => {
      const [hostName, deviceId] = key.split(':');
      if (!deviceId || isDeviceAllowed(hostName, deviceId)) next.set(key, ui);
      else changed = true;
    });
    return changed ? next : prev;
  });
}, [isDeviceAllowed]);
```

</div>

### Scripts are one line in the selector

The script picker hides the scripts that the workspace does not allow. Test cases and campaigns always show.

<div data-technical>

Workspace scope goes into the `UnifiedExecutableSelector`'s `itemFilter` prop:

```ts
if (item.type === 'script' && !isScriptAllowed(item.id)) return false;
```

Test cases are exempt — a separate executable type, and `script_filter` lists script names. Campaigns too: a campaign contains many scripts, so filtering by its display name would be arbitrary.

</div>

### History is filtered twice

The history is filtered on the server, and then again in the browser. The second pass catches runs that were tracked locally and never went through the server.

<div data-technical>

Server-side as above, then a client-side pass to catch the locally-tracked rows that never went through the query. `RunExecutionsContext` holds the scope in a ref so switching workspace doesn't recreate `refresh()` and tear down the `/system` socket:

```ts
scopeRef.current = {
  deviceFilter: activeWorkspace?.device_filter,
  scriptFilter: activeWorkspace?.script_filter,
};
useEffect(() => { void refresh(); }, [refresh, activeWorkspace?.id]);
```

Then in `visibleExecutions` — normalize and filter first, slice to the limit **last**:

```ts
.filter((execution) => {
  if (execution.deviceId && !isDeviceAllowed(execution.hostName, execution.deviceId)) return false;
  if (execution.executionType === 'script' && !isScriptAllowed(execution.scriptName)) return false;
  return true;
})
.slice(0, RUN_TESTS_HISTORY_LIMIT);
```

</div>

---

## Gotchas

Things that break quietly if you forget them.

- **Script names differ between two lists.** Handle both the bare name and the name ending in `.py`.
- **Filter first, limit last.** Otherwise a burst of campaign runs can push out every script run.
- **Reset on switch.** Reload the history, prune hidden devices from the selection, and reset saved filters when the workspace changes.

<div data-technical>

- **Script names differ between two lists.** One list gives bare names, the other gives names ending in `.py`. Handle both, or half the scripts disappear. Both the app and the server do this.
- **Filter first, limit last.** If you cut the list short before filtering, a burst of campaign runs can push out every script run.
- **Old rows after a switch.** If you do not reload the history when the workspace changes, the old workspace's rows stay on screen.
- **Old selections after a switch.** A selected device can become hidden mid-session. Remove it from the selection. Do not just hide the row.
- **Saved filters after a switch.** Pages that remember their filters in the browser must reset them when the workspace changes. See `BUG-0011`.

| Trap | Why it bites |
|---|---|
| **`.py` name drift** | `/server/script/list` returns bare names, `/server/executable/list` returns `name.py`. Normalize in both directions or half the scripts vanish. Both `isScriptAllowed` and the backend do this. |
| **Slicing before filtering** | Run every tab and workspace filter, *then* apply the row limit. Slicing early lets a burst of campaign rows crowd out every script row. `normalizeExecutionHistory` is deliberately called with `Infinity`. |
| **Stale rows on switch** | Without the refetch keyed on `activeWorkspace?.id`, the previous workspace's rows stay on screen — they were filtered server-side for the old scope. |
| **Stale selections on switch** | A selected device can become invisible mid-session. Prune the selection, don't just hide the row. |
| **Persisted filters on switch** | Pages with `localStorage`-persisted filters need their own reset on workspace change — see `BUG-0011`. |

</div>

---

## Implementation files

<div data-technical>

Where the code lives. Useful if you are changing this feature.

| File | Role |
|---|---|
| `frontend/src/contexts/workspace/WorkspaceContext.tsx` | Active workspace + `isDeviceAllowed` / `isScriptAllowed` / `isPathHidden` |
| `frontend/src/hooks/pages/useWorkspaces.ts` | `Workspace` type, `useUserWorkspaces`, `usePublicWorkspaces`, CRUD |
| `frontend/src/components/common/ScopePicker.tsx` | The header picker (server, workspace, project); the Workspace column lists the user's workspaces |
| `frontend/src/hooks/useTargetSelection.ts` | Device scoping choke point + selection pruning |
| `frontend/src/pages/RunTests.tsx` | Script selector `itemFilter`, `visibleExecutions` history filter |
| `frontend/src/contexts/RunExecutionsContext.tsx` | Server-side scope on the history fetch, refetch on workspace change |
| `frontend/src/hooks/useDeployment.ts` | `getRecentExecutions(scope)` — builds the query params |
| `frontend/src/pages/Dashboard.tsx`, `Rec.tsx`, `TestReports.tsx` | Other `isDeviceAllowed` consumers |
| `frontend/src/pages/Workspaces.tsx` | Admin UI — edits `device_filter` / `script_filter` / `hidden_pages` |
| `backend_server/src/routes/server_workspaces_routes.py` | `/server/workspaces` CRUD + `/user/<id>` |
| `backend_server/src/routes/server_deployment_routes.py` | `executions/recent` server-side scoping before the limit |

</div>

---

## Testing it

Make two workspaces whose device lists do not overlap. Switch between them while a run is in progress.

<div data-technical>

Two workspaces whose `device_filter`s do not overlap, switched back and forth with a run in progress. That single flow exercises the selection pruning, the history refetch and the slice order at once.

</div>

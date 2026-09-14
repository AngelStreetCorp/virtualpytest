# Fine-Grained Permission System — Implementation Plan

> **Status:** SHIPPED. This is the historical design doc — treat "Current State Inventory" below
> as the *before* picture, not current reality. The `namespace:action` permission format proposed
> here (e.g. `testcases:hide`, `builder.campaign:view`, `campaigns:execute`) is now the real
> `Permission` type — see `frontend/src/types/auth.ts` and the `_ROLE_PERMISSIONS` dict in
> `backend_server/src/routes/server_permissions_routes.py`. The admin UI for managing
> role/user/team permissions is `frontend/src/pages/Users.tsx`.
> **Author:** Generated from full codebase audit
> **Last updated:** 2026-03-16 (design); shipped since — see note above

---

## 1. Problem Statement

The current permission system is **page-level only**. It answers "can the user see this page?" but not "can the user perform this action on this page?".

### Use cases that cannot be expressed today

| Use case | Current state | Required |
|----------|--------------|---------|
| User can execute tests + campaigns but NOT build campaigns or see the builder page | ❌ `run_tests` grants entire execution section | `execution:run_test`, `execution:run_campaign` without `builder.campaign:view` |
| User can view test cases but NOT hide them | ❌ `edit_test_cases` grants all edit actions | `testcases:view` without `testcases:hide` |
| User belongs to "QA Team" AND "On-Call Team" and inherits both teams' permissions | ❌ UI only exposes one team (profiles.team_id) | multi-team membership with permission union |
| Team "Test Runners" grants `execution:run_test` to all its members regardless of role | ❌ Teams have no permissions column | `teams.permissions JSONB` |
| Admin explicitly denies a tester from accessing the Langfuse plugin | ❌ No deny mechanism | `profiles.denied_permissions JSONB` |

---

## 2. Current State Inventory

### What exists

```
profiles table:
  role: 'admin' | 'tester' | 'viewer'          ← 3 coarse presets
  permissions: JSONB []                          ← extra grants (DB ready, UI never used)
  team_id: UUID                                  ← primary team only (UI exposes this)

team_members table:
  team_id, user_id, role: owner|admin|member     ← many-to-many (DB ready, UI partially used)

teams table:
  id, name, description, tenant_id, is_default   ← NO permissions column

Permission type (frontend, 15 values):
  view_dashboard, run_tests, create_test_cases,
  edit_test_cases, delete_test_cases, view_reports,
  api_testing, jira_integration, manage_devices,
  manage_settings, manage_users, view_monitoring,
  create_campaigns, edit_campaigns, delete_campaigns

Navigation: premiumKey → featureFlags.getNavVisibility()
  ← build-time env vars, NOT runtime permission checks
  ← 'ai', 'langfuse', 'postman', 'jira', 'slack',
     'code-deployment', 'cicd-reports' are NOT in Permission type
```

### What is missing

1. No `denied_permissions` on `profiles`
2. No `permissions` on `teams`
3. No action-level permissions (only page-level)
4. `premiumKey` nav items not wired to `PermissionContext`
5. No permission test coverage beyond auth presence/absence
6. Users page edit dialog does not expose `permissions` JSONB
7. Team page does not show member management inline

---

## 3. Permission Model

### Format: `resource:action`

Inspired by AWS IAM (`s3:GetObject`). Colon-separated, easy to glob (`testcases:*`).

### Full permission vocabulary (~58 permissions)

```
RESOURCE                ACTION(S)
─────────────────────────────────────────────────────────────────
dashboard               view

device_control          view, execute, reboot, restart_streams

testcases               view, create, edit, delete, hide
campaigns               view, create, edit, delete, execute

builder.test            view, use
builder.campaign        view, use

execution.run           view, run_test, run_campaign
execution.monitor       view
execution.build         view, use

reports.tests           view
reports.campaigns       view
reports.models          view
reports.dependency      view

monitoring.incidents    view
monitoring.heatmap      view
monitoring.ai_queue     view

interface               view, create, edit, delete

ai_agent                view, use

plugins.grafana         view
plugins.langfuse        view
plugins.postman         view
plugins.jira            view, manage
plugins.slack           view

settings.general        view, edit
settings.models         view, edit
settings.code_deploy    view, use
settings.cicd           view
settings.branding       view, edit
settings.status         view

org.users               view, edit, delete
org.teams               view, create, edit, delete, manage_members
org.invite              send
```

### Role presets (bundles — still needed for UX)

Roles become **named defaults**, not hard constraints. An admin can grant/deny individual permissions on top of a role.

| Role | Included by default |
|------|-------------------|
| `admin` | all permissions |
| `tester` | dashboard:view, device_control:view/execute, testcases:view/create/edit, campaigns:view/create/edit/execute, builder.test:view/use, execution.run:view/run_test/run_campaign, execution.monitor:view, reports.*:view, monitoring.*:view, ai_agent:view/use, plugins.jira:view/manage, interface:view |
| `viewer` | dashboard:view, testcases:view, campaigns:view, reports.*:view, monitoring.*:view, settings.status:view |
| `runner` *(new)* | dashboard:view, execution.run:view/run_test/run_campaign, execution.monitor:view, reports.tests:view, reports.campaigns:view |
| `developer` *(new)* | all except org.* and settings.general/models |

### Permission resolution order (merge)

```
effective_permissions =
    ROLE_DEFAULTS[user.role]          (hardcoded presets as starting point)
  ∪ team_permissions[]               (union of ALL teams the user belongs to)
  ∪ user.permissions                 (individual grants on top)
  − user.denied_permissions          (explicit denials — highest priority)
```

`denied_permissions` always wins. An admin can take away a role's default permission from a specific user.

---

## 4. Use Case Mappings

### UC1 — Can run tests/campaigns, cannot build campaigns

```
User role:   viewer  (or a new 'runner' role)
Team:        "Test Runners"
  team.permissions: [
    "execution.run:view",
    "execution.run:run_test",
    "execution.run:run_campaign",
    "execution.monitor:view",
    "reports.tests:view",
    "reports.campaigns:view"
  ]
User individual grants:   []
User denied_permissions:  ["builder.campaign:view", "execution.build:view"]

→ Run Tests page:    VISIBLE  (execution.run:view)
→ Build Campaign tab: HIDDEN   (builder.campaign:view denied)
→ Execute test btn:  VISIBLE  (execution.run:run_test)
→ Execute campaign:  VISIBLE  (execution.run:run_campaign)
→ Campaign Builder:  HIDDEN   (builder.campaign:view denied)
```

### UC2 — Can see test cases, cannot hide them

```
User role:  viewer
User permissions: ["testcases:view"]
User denied_permissions: []  (hide not granted = not available)

→ Test Cases page:  VISIBLE  (testcases:view)
→ Hide button:      HIDDEN   (testcases:hide not in effective set)
→ Edit button:      HIDDEN   (testcases:edit not granted)
→ Create button:    HIDDEN   (testcases:create not granted)
```

### UC3 — User in two teams, union of both

```
User role: viewer
Teams:
  "QA Engineers"  → permissions: [testcases:*, campaigns:*, builder.test:*]
  "On-Call Ops"   → permissions: [monitoring.*:view, device_control:view/reboot]

Effective = viewer_defaults ∪ QA_permissions ∪ OnCall_permissions
→ Can do QA work AND on-call monitoring
```

---

## 5. Database Changes

### Migration 028 — Add permissions to teams, denied_permissions to profiles

```sql
-- Add team-level permissions
ALTER TABLE public.teams
  ADD COLUMN IF NOT EXISTS permissions JSONB DEFAULT '[]'::jsonb;

-- Add explicit denials to profiles
ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS denied_permissions JSONB DEFAULT '[]'::jsonb;

-- Comment
COMMENT ON COLUMN public.teams.permissions IS
  'Array of permission strings (resource:action) granted to all team members';
COMMENT ON COLUMN public.profiles.denied_permissions IS
  'Array of permission strings explicitly denied for this user (overrides role + team grants)';
```

### Migration 029 — Permission resolution RPC

```sql
-- Server-side helper to compute effective permissions for a user
CREATE OR REPLACE FUNCTION public.get_user_effective_permissions(p_user_id UUID)
RETURNS JSONB AS $$
DECLARE
  v_profile      RECORD;
  v_team_perms   JSONB   := '[]'::jsonb;
  v_all_grants   JSONB;
  v_denied       JSONB;
  v_effective    JSONB;
BEGIN
  -- Load profile
  SELECT role, permissions, denied_permissions
  INTO v_profile
  FROM public.profiles WHERE id = p_user_id;

  -- Collect all team permissions
  SELECT COALESCE(jsonb_agg(DISTINCT elem), '[]'::jsonb)
  INTO v_team_perms
  FROM public.team_members tm
  JOIN public.teams t ON t.id = tm.team_id
  CROSS JOIN jsonb_array_elements_text(COALESCE(t.permissions, '[]'::jsonb)) AS elem
  WHERE tm.user_id = p_user_id;

  -- Union: profile.permissions + team permissions
  v_all_grants := COALESCE(v_profile.permissions, '[]'::jsonb) || v_team_perms;

  -- Remove duplicates and apply denials
  SELECT jsonb_agg(DISTINCT elem)
  INTO v_effective
  FROM jsonb_array_elements_text(v_all_grants) AS elem
  WHERE elem NOT IN (
    SELECT jsonb_array_elements_text(COALESCE(v_profile.denied_permissions, '[]'::jsonb))
  );

  RETURN COALESCE(v_effective, '[]'::jsonb);
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;
```

---

## 6. Backend Changes

### 6.1 Expand `auth_middleware.py`

- Update `ROLE_PERMISSIONS` dict with new `resource:action` strings
- Add `runner` and `developer` role defaults
- `require_permission()` decorator must accept new format

### 6.2 New endpoint: `GET /server/users/:id/permissions`

Returns the effective permission set for a user (computed by `get_user_effective_permissions` RPC):

```json
{
  "success": true,
  "user_id": "...",
  "role": "tester",
  "role_permissions": ["dashboard:view", "testcases:view", ...],
  "team_permissions": ["execution.run:run_test", ...],
  "individual_grants": ["plugins.jira:manage"],
  "denied_permissions": ["builder.campaign:view"],
  "effective": ["dashboard:view", "testcases:view", "execution.run:run_test", ...]
}
```

### 6.3 Update `PUT /server/users/:id`

Accept `permissions` and `denied_permissions` arrays in body.

### 6.4 Update `PUT /server/teams/:id`

Accept `permissions` array in body.

### 6.5 New endpoint: `GET /server/permissions/matrix`

Returns the full permission matrix for all users (admin only):

```json
{
  "success": true,
  "permissions": ["dashboard:view", "testcases:view", ...],
  "users": [
    {
      "id": "...", "email": "alice@...", "role": "tester",
      "effective": ["dashboard:view", "testcases:view", "testcases:hide", ...]
    }
  ]
}
```

---

## 7. Frontend Changes

### 7.1 Expand `types/auth.ts`

Replace 15 flat strings with 58 `resource:action` strings. Keep backward compatibility mapping for migration period.

### 7.2 Update `PermissionContext.tsx`

Change merge logic:
```
effective = ROLE_DEFAULTS[role]
          ∪ all team permissions (requires new API call or include in profile fetch)
          ∪ profile.permissions
          − profile.denied_permissions
```

Profile fetch must include team permissions (add `teams_permissions` to `/server/auth/profile` response).

### 7.3 Wire `premiumKey` → `PermissionContext`

In `Navigation_Dropdown.tsx`, replace `getNavVisibility(premiumKey)` with `canAccess(premiumKey_to_permission_map[premiumKey])` — fall back to `getNavVisibility` for build-time overrides.

premiumKey → permission mapping:
```
'ai'              → 'ai_agent:view'
'langfuse'        → 'plugins.langfuse:view'
'postman'         → 'plugins.postman:view'
'jira'            → 'plugins.jira:view'
'slack'           → 'plugins.slack:view'
'code-deployment' → 'settings.code_deploy:view'
'cicd-reports'    → 'settings.cicd:view'
```

### 7.4 Update `Users.tsx` — permission matrix in edit dialog

Add tabs to edit dialog:
1. **Profile** — name, role, team assignments (multi-select, not single dropdown)
2. **Permissions** — checkbox grid grouped by resource:
   - Pre-checked from role (disabled, labelled "via role")
   - Pre-checked from teams (disabled, labelled "via team: QA")
   - Toggleable extras (write to `permissions`)
   - Red toggle for denials (write to `denied_permissions`)

### 7.5 Update `Teams.tsx` — permissions on team

Add "Permissions" section to team create/edit dialog — same checkbox grid, writes to `teams.permissions`.

### 7.6 Add `<PermissionGate>` to in-page actions

Key locations requiring action-level gates:

| Page | Action | Permission required |
|------|--------|-------------------|
| `TestCaseEditor` | Hide button | `testcases:hide` |
| `TestCaseEditor` | Delete button | `testcases:delete` |
| `TestCaseEditor` | Create button | `testcases:create` |
| `CampaignEditor` | Delete campaign | `campaigns:delete` |
| `RunTests` | Execute test button | `execution.run:run_test` |
| `RunTests` | Execute campaign button | `execution.run:run_campaign` |
| `Dashboard` | Reboot host | `device_control:reboot` |
| `Dashboard` | Restart service | `device_control:execute` |
| `Settings` (Branding tab) | Save | `settings.branding:edit` |
| `Users` / `Teams` pages | All actions | `org.users:edit`, `org.teams:edit` |

### 7.7 New `Users` page — Permission Matrix tab

Second tab on Users page showing a cross-user matrix:
- Rows: users
- Columns: permissions (grouped by resource)
- Cell: filled = effective, outlined = via team, star = individual grant, red = denied
- Click a cell to toggle individual grant/denial inline

---

## 8. Test Plan

All tests go in `tests/backend_server/test_permissions.py`.
Pattern: follows existing `conftest.py` fixtures (`get`, `api_headers`, `team_id`).
New fixtures needed: `admin_jwt`, `tester_jwt`, `viewer_jwt`, `runner_jwt`.

### 8.1 Role baseline tests

```python
# test_permissions.py

class TestRoleBaselines:

    def test_admin_can_access_users_endpoint(admin_jwt, base_url):
        # GET /server/users → 200

    def test_tester_cannot_access_users_endpoint(tester_jwt, base_url):
        # GET /server/users → 403

    def test_viewer_cannot_access_users_endpoint(viewer_jwt, base_url):
        # GET /server/users → 403

    def test_admin_can_update_user_role(admin_jwt, base_url):
        # PUT /server/users/:id { role: 'tester' } → 200

    def test_tester_cannot_update_user_role(tester_jwt, base_url):
        # PUT /server/users/:id { role: 'viewer' } → 403

    def test_viewer_can_access_dashboard(viewer_jwt, base_url):
        # GET /server/health (as proxy) → 200

    def test_viewer_cannot_run_tests(viewer_jwt, base_url):
        # POST /server/script/execute → 403
```

### 8.2 UC1 — Run tests/campaigns, blocked from builder

```python
class TestUC1RunnerCannotBuild:

    def test_runner_can_execute_test(runner_jwt, base_url, team_id):
        # POST /server/script/execute → 200 or 202 (not 403)

    def test_runner_can_execute_campaign(runner_jwt, base_url, team_id):
        # POST /server/campaigns/execute → 200 or 202 (not 403)

    def test_runner_cannot_create_campaign(runner_jwt, base_url, team_id):
        # POST /server/campaigns/createCampaign → 403

    def test_runner_cannot_create_testcase(runner_jwt, base_url, team_id):
        # POST /server/testcases → 403

    def test_runner_can_view_testcases(runner_jwt, base_url, team_id):
        # GET /server/testcases → 200

    def test_runner_can_view_campaigns(runner_jwt, base_url, team_id):
        # GET /server/campaigns/getAllCampaigns → 200

    def test_runner_can_view_reports(runner_jwt, base_url, team_id):
        # GET /server/script-results → 200
```

### 8.3 UC2 — View test cases but cannot hide

```python
class TestUC2ViewerCannotHide:

    def test_viewer_can_list_testcases(viewer_jwt, base_url, team_id):
        # GET /server/testcases → 200, list returned

    def test_viewer_cannot_hide_testcase(viewer_jwt, base_url, team_id, testcase_id):
        # PATCH /server/testcases/:id/hide → 403

    def test_viewer_cannot_edit_testcase(viewer_jwt, base_url, team_id, testcase_id):
        # PUT /server/testcases/:id → 403

    def test_viewer_cannot_delete_testcase(viewer_jwt, base_url, team_id, testcase_id):
        # DELETE /server/testcases/:id → 403

    def test_tester_with_grant_can_hide_testcase(custom_tester_jwt, base_url, team_id, testcase_id):
        # tester with testcases:hide explicit grant
        # PATCH /server/testcases/:id/hide → 200

    def test_tester_with_denial_cannot_hide(denied_tester_jwt, base_url, team_id, testcase_id):
        # tester (who normally can hide) with denied_permissions: ["testcases:hide"]
        # PATCH /server/testcases/:id/hide → 403
```

### 8.4 Team permission inheritance

```python
class TestTeamPermissions:

    def test_viewer_in_team_with_execution_perms_can_run(
        viewer_in_runner_team_jwt, base_url, team_id
    ):
        # viewer role, but member of team with execution.run:run_test
        # POST /server/script/execute → 200 or 202 (not 403)

    def test_viewer_without_team_cannot_run(viewer_jwt, base_url, team_id):
        # POST /server/script/execute → 403

    def test_user_in_two_teams_gets_union_of_perms(dual_team_jwt, base_url, team_id):
        # member of "QA Team" (testcases:*) + "On-Call Team" (monitoring:*)
        # GET /server/testcases → 200
        # GET /server/monitoring endpoints → 200

    def test_team_permission_update_propagates(admin_jwt, base_url, viewer_jwt):
        # 1. viewer cannot run test
        # 2. admin updates team to include execution.run:run_test
        # 3. viewer (in that team) can now run test
```

### 8.5 Denied permissions override

```python
class TestDeniedPermissions:

    def test_denied_overrides_role(tester_with_denial_jwt, base_url, team_id):
        # tester role normally has campaigns:create
        # but denied_permissions: ["campaigns:create"]
        # POST /server/campaigns/createCampaign → 403

    def test_denied_overrides_team_grant(complex_user_jwt, base_url, team_id):
        # team grants execution.run:run_test
        # user.denied_permissions: ["execution.run:run_test"]
        # POST /server/script/execute → 403

    def test_removing_denial_restores_access(admin_jwt, base_url, test_user_id):
        # 1. Set denied_permissions: ["testcases:create"] → POST testcase = 403
        # 2. Remove denial → POST testcase = 200/201
```

### 8.6 Permission matrix API

```python
class TestPermissionMatrixAPI:

    def test_get_user_effective_permissions(admin_jwt, base_url, user_id):
        # GET /server/users/:id/permissions → 200
        # response has: role, role_permissions, team_permissions,
        #               individual_grants, denied_permissions, effective

    def test_get_permission_matrix(admin_jwt, base_url):
        # GET /server/permissions/matrix → 200
        # response has: permissions[], users[{id, email, role, effective[]}]

    def test_non_admin_cannot_get_matrix(tester_jwt, base_url):
        # GET /server/permissions/matrix → 403

    def test_effective_permissions_reflect_denials(admin_jwt, base_url, user_id):
        # PUT /server/users/:id with denied_permissions: ["testcases:delete"]
        # GET /server/users/:id/permissions
        # effective does NOT contain testcases:delete
```

### 8.7 Organisation management

```python
class TestOrgManagement:

    def test_admin_can_list_all_users(admin_jwt, base_url):
        # GET /server/users → 200, list of user objects

    def test_admin_can_assign_user_to_multiple_teams(admin_jwt, base_url, user_id):
        # POST /server/teams/:team1/members { user_id } → 200
        # POST /server/teams/:team2/members { user_id } → 200
        # GET /server/users/:user_id → user.teams has both teams

    def test_admin_can_remove_user_from_team(admin_jwt, base_url, user_id, team_id):
        # DELETE /server/teams/:team_id/members/:user_id → 200

    def test_team_owner_can_manage_own_team(team_owner_jwt, base_url, owned_team_id):
        # POST /server/teams/:owned_team_id/members → 200

    def test_team_member_cannot_manage_team(member_jwt, base_url, team_id):
        # POST /server/teams/:team_id/members → 403

    def test_admin_can_set_team_permissions(admin_jwt, base_url, team_id):
        # PUT /server/teams/:team_id { permissions: ["execution.run:run_test"] } → 200
        # GET /server/teams/:team_id → team.permissions contains the new permission
```

### 8.8 New conftest fixtures needed

```python
# Add to tests/backend_server/conftest.py

@pytest.fixture(scope="session")
def admin_jwt():
    """JWT for an admin user. From ADMIN_TEST_JWT env var."""
    return os.environ.get("ADMIN_TEST_JWT", "")

@pytest.fixture(scope="session")
def tester_jwt():
    """JWT for a tester user. From TESTER_TEST_JWT env var."""
    return os.environ.get("TESTER_TEST_JWT", "")

@pytest.fixture(scope="session")
def viewer_jwt():
    """JWT for a viewer user. From VIEWER_TEST_JWT env var."""
    return os.environ.get("VIEWER_TEST_JWT", "")

@pytest.fixture(scope="session")
def runner_jwt():
    """JWT for a user with runner role or equivalent permissions. From RUNNER_TEST_JWT env var."""
    return os.environ.get("RUNNER_TEST_JWT", "")

def jwt_headers(token: str) -> dict:
    """Build headers dict for a given JWT token."""
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
```

New CI environment variables:
```
ADMIN_TEST_JWT      JWT for admin user (Supabase-issued)
TESTER_TEST_JWT     JWT for tester user
VIEWER_TEST_JWT     JWT for viewer user
RUNNER_TEST_JWT     JWT for runner-role user
```

---

## 9. Implementation Order

| Step | What | Files touched | Risk |
|------|------|--------------|------|
| 1 | SQL migrations (028, 029) | `setup/db/schema/028_*.sql`, `029_*.sql` | Low — additive only |
| 2 | Expand `Permission` type, `ROLE_PERMISSIONS` | `frontend/src/types/auth.ts` | Low |
| 3 | Update `auth_middleware.py` role defaults | `backend_server/src/lib/auth_middleware.py` | Medium — must not break existing |
| 4 | Update `PermissionContext` merge logic | `frontend/src/contexts/auth/PermissionContext.tsx` | Medium |
| 5 | New backend endpoints (permissions, matrix) | New route file + register | Low |
| 6 | Update `PUT /server/users/:id` + `PUT /server/teams/:id` | `server_users_routes.py`, `server_teams_routes.py`, `users_db.py`, `teams_db.py` | Low |
| 7 | Write `tests/backend_server/test_permissions.py` | New test file | Low |
| 8 | Wire `premiumKey` → `PermissionContext` | `Navigation_Dropdown.tsx` | Low |
| 9 | `Users.tsx` — multi-team + permission checkboxes | `Users.tsx` | Medium |
| 10 | `Teams.tsx` — team permissions editor | `Teams.tsx` | Medium |
| 11 | `<PermissionGate>` on in-page actions | Per-feature, ongoing | Low per change |
| 12 | Permission Matrix tab on Users page | `Users.tsx` | Medium |
| 13 | New Org page (invites, audit log) | New page + backend | High |

Steps 1–7 are the **foundation** — must be done first and in order.
Steps 8–12 can be parallelized once the foundation is in place.
Step 13 is independent and can be deferred.

---

## 10. What NOT to change

- **Supabase `auth.users` table** — managed by Supabase, never touch directly
- **`profiles.role` column** — keep the 3 built-in roles, just expand what they resolve to
- **`team_members.role` (owner/admin/member)** — this is the *within-team* role, separate from the system role
- **`isAuthEnabled` flag** — keep the opt-out path working; all permission checks must be no-ops when auth is disabled
- **Auto-sign bypass** — keep working for E2E tests; auto-sign role (`AUTO_SIGN_ROLE`) should map to effective permissions the same way

---

## 11. Open Questions

1. **Should `runner` be a built-in role or just a team template?**
   Recommendation: team template. Fewer built-in roles = simpler mental model.

2. **Should team permissions stack or be a union?**
   Decision: union (most permissive wins across teams). Denials on the user still win.

3. **Should the permission matrix be visible to team owners (not just admins)?**
   Decision: team owners see their team's members only, not the full org matrix.

4. **Are permissions checked server-side on every API call or only on the first render?**
   Decision: both. Server-side is the source of truth. Frontend gates are UX only.

5. **Do we store the full permission set in the JWT or fetch on demand?**
   Current Supabase setup stores `permissions` in `user_metadata`. Recommendation: keep that approach but add team_permissions to the `/server/auth/profile` response so `PermissionContext` gets a fully resolved set without extra calls.

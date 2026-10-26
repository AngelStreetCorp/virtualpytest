import React, { createContext, useContext, useEffect, useState, useCallback, useMemo } from 'react';
import { useAuth } from '../../hooks/auth/useAuth';
import { usePermissions } from '../../hooks/auth/usePermissions';
import { requiredPermissionForPath } from '../../types/auth';
import { useUserWorkspaces, usePublicWorkspaces, Workspace } from '../../hooks/pages/useWorkspaces';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { useDeviceFlags, DeviceFlag } from '../../hooks/useDeviceFlags';
import { useCurrentProject, useProjectExecutables } from '../../hooks/common/useCurrentProject';

const ACTIVE_WORKSPACE_KEY = 'vpt_active_workspace';

/**
 * The four executable kinds the G9 project pipe scopes. Anything outside
 * this union (e.g. nightly campaigns in the future) is not project-scoped
 * and `isExecutableAllowed` returns true for it.
 */
export type ExecutableType = 'script' | 'testcase' | 'virtual_script' | 'campaign';

interface WorkspaceContextValue {
  userWorkspaces: Workspace[];
  activeWorkspace: Workspace | null;
  setActiveWorkspace: (id: string | null) => void;
  isLoadingWorkspaces: boolean;
  /**
   * True when the given `hostName:deviceId` target is allowed:
   *   * inside the user's device limit (team ∩ role ∩ user, TASK-31) and
   *   * inside the active workspace's filter and
   *   * (no project selected OR the device's `device_flags.flags` shares at
   *     least one tag name with the current project).
   * Each check passes when there is no limit / no active workspace / no
   * project. Keys use the `TargetPanel` format. A filter on what is shown,
   * not authorization.
   */
  isDeviceAllowed: (hostName: string, deviceId: string) => boolean;
  /**
   * The same rule as a key list for server-side filters: the user's device
   * limit ∩ the active workspace's device_filter ∩ (project's device
   * intersection, when a project is selected). `null` = no device filtering
   * at all.
   */
  deviceFilter: string[] | null;
  /**
   * True when the given script NAME is allowed in the active workspace and
   * (when a project is selected) the name resolves to an executable in the
   * project's tagged set. Returns true when no workspace AND no project
   * is active. Handles both bare names (`goto_home`) and `.py`-suffixed
   * names from /server/executable/list.
   *
   * NOTE: the G9 selectors that already pass the `(type, id)` pair should
   * prefer `isExecutableAllowed(type, id)` — name-based filtering has
   * collision risk between script / testcase / virtual_script with the
   * same name. This entry point is kept for the existing call sites
   * (RecRunScriptPanel, RunTests) where the caller only has the name.
   */
  isScriptAllowed: (scriptName: string) => boolean;
  /**
   * The G9 entry point (TASK-65 §14.2). True when the executable is
   * allowed by the active workspace AND (no project selected OR the
   * `(type, id)` pair is in the current project's tagged set).
   *
   * Returns true when no workspace AND no project is active. The
   * WorkspaceContext caches the project's executables via react-query so
   * the G9 selectors can call this on every render without an extra
   * request.
   */
  isExecutableAllowed: (executableType: ExecutableType, executableId: string) => boolean;
  /**
   * The same rule as a list of `(type, id)` pairs for the G9 selectors that
   * want to filter an existing list (the campaign selector, the build
   * campaign rail). Returns `null` when no project is selected, meaning
   * "no project scope — don't filter". A workspace scope without a project
   * scope returns an empty array (workspace denied everything).
   */
  projectExecutableIds: Map<ExecutableType, Set<string>> | null;
  /**
   * The current project's tag names, lowercased. Exposed so the G9
   * selectors that filter on a custom data shape (e.g. QuickTest's
   * settings) can apply the project scope directly without rebuilding
   * the tag intersection themselves. Empty array when no project is
   * selected OR the project has no tag yet.
   */
  projectTagNames: string[];
  /**
   * The script-name list that satisfies BOTH the active workspace's
   * `script_filter` AND the current project's tagged scripts (when a
   * project is selected). Returns `null` when no workspace AND no
   * project is active (caller treats that as "no script scope at all").
   * Used by `useDeployment` and `runManagementApi` to send a server-side
   * `script_filter` query parameter.
   */
  scriptFilter: string[] | null;
  /**
   * True when the given route path is hidden by the active workspace's
   * `hidden_pages`. Returns false when no workspace is active.
   */
  isPathHidden: (path: string) => boolean;
}

const WorkspaceContext = createContext<WorkspaceContextValue | undefined>(undefined);

export const useWorkspaceContext = (): WorkspaceContextValue => {
  const context = useContext(WorkspaceContext);
  if (!context) {
    throw new Error('useWorkspaceContext must be used within WorkspaceProvider');
  }
  return context;
};

interface WorkspaceProviderProps {
  children: React.ReactNode;
}

export const WorkspaceProvider: React.FC<WorkspaceProviderProps> = ({ children }) => {
  const { user, isLoading: isAuthLoading } = useAuth();
  const { canAccess } = usePermissions();
  const userId = user?.id ?? '';
  // Signed-in users get memberships + public workspaces via the RPC.
  // Anonymous users (no Supabase session → no userId) fall back to the plain
  // list endpoint filtered to `is_public` — since /server/workspaces has no
  // RLS gate when ENFORCE_FRONTEND_JWT is off, public workspaces remain
  // visible without a JWT.
  //
  // `!userId` alone is not "anonymous", it is also "auth has not resolved yet",
  // which is true on the first render of every page load. Without the isLoading
  // gate a signed-in user fires the anonymous request too, and that one hits
  // GET /server/workspaces — which needs org.workspaces:view. An admin gets a 200
  // and never notices; every viewer and tester got a 403 on every navigation.
  const { data: membershipWorkspaces = [], isLoading: isLoadingMembership } = useUserWorkspaces(userId);
  const { data: publicOnlyWorkspaces = [], isLoading: isLoadingPublic } = usePublicWorkspaces(!userId && !isAuthLoading);
  const userWorkspaces = userId ? membershipWorkspaces : publicOnlyWorkspaces;
  const isLoadingWorkspaces = userId ? isLoadingMembership : isLoadingPublic;
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(() => {
    try {
      return localStorage.getItem(ACTIVE_WORKSPACE_KEY) ?? null;
    } catch {
      return null;
    }
  });

  // When workspaces load, validate the stored activeWorkspaceId is still valid
  useEffect(() => {
    if (isLoadingWorkspaces) return;
    if (activeWorkspaceId && !userWorkspaces.find((ws) => ws.id === activeWorkspaceId)) {
      setActiveWorkspaceId(null);
      try {
        localStorage.removeItem(ACTIVE_WORKSPACE_KEY);
      } catch {
        // ignore
      }
    }
  }, [userWorkspaces, isLoadingWorkspaces, activeWorkspaceId]);

  const setActiveWorkspace = useCallback((id: string | null) => {
    setActiveWorkspaceId(id);
    try {
      if (id === null) {
        localStorage.removeItem(ACTIVE_WORKSPACE_KEY);
      } else {
        localStorage.setItem(ACTIVE_WORKSPACE_KEY, id);
      }
    } catch {
      // ignore storage errors
    }
  }, []);

  const activeWorkspace = userWorkspaces.find((ws) => ws.id === activeWorkspaceId) ?? null;

  // The user's effective device limit (GET /server/users/<id>/scope); null = every device.
  const { data: effectiveDevices = null } = useQuery({
    queryKey: ['user-device-scope', user?.id],
    queryFn: async (): Promise<string[] | null> => {
      const scope: { effective_devices: string[] | null } = await api.get(
        buildServerUrl(`/server/users/${user!.id}/scope`),
      );
      return scope.effective_devices ?? null;
    },
    enabled: !!user?.id,
    staleTime: 5 * 60 * 1000,
  });

  // ----- G9: project + project executables ---------------------------------
  // `useCurrentProject` reads `localStorage["virtualpytest:project_id"]` and
  // exposes the current project (with its tag names). The G9 selectors
  // consume `isExecutableAllowed` from this provider, which in turn reads
  // the executables cache via `useProjectExecutables`. The provider mounts
  // once at the app root, so this fires one GET per project change.
  const { currentProject, tagNames } = useCurrentProject();
  const { data: projectExecutables } = useProjectExecutables(currentProject?.id ?? null);

  // ----- G9: device flag set (per-device tag list) -------------------------
  // The project filter on devices is "device_flags.flags ∩ project_tag_names
  // ≠ ∅". `useDeviceFlags` fetches the full table once (a few hundred rows
  // max) and exposes the per-device flag list. We also expose a quick lookup
  // for the deviceFilter intersection below.
  const { deviceFlags } = useDeviceFlags();

  // Build a `hostName:deviceId -> flag[]` map once per deviceFlags change.
  const deviceFlagsByKey = useMemo((): Map<string, string[]> => {
    const m = new Map<string, string[]>();
    for (const df of deviceFlags as DeviceFlag[]) {
      if (!df || !df.host_name) continue;
      const key = `${df.host_name}:${df.device_id}`;
      m.set(key, (df.flags || []).map((f) => (f || '').toString().toLowerCase()));
    }
    return m;
  }, [deviceFlags]);

  // The set of device keys whose flag set intersects the project's tag
  // names. Null when no project is selected (means "no project scope").
  // The set is empty (and not null) when the project has tags but no
  // device carries one of them yet (e.g. freshly created project).
  const projectDeviceKeys = useMemo((): Set<string> | null => {
    if (!currentProject) return null;
    if (tagNames.length === 0) return new Set<string>(); // no tag = no device passes
    const out = new Set<string>();
    for (const [key, flags] of deviceFlagsByKey.entries()) {
      if (flags.some((f) => tagNames.includes(f))) out.add(key);
    }
    return out;
  }, [currentProject, tagNames, deviceFlagsByKey]);

  // Build a `type -> Set<id>` map for fast isExecutableAllowed lookups.
  // Null when no project is selected.
  const projectExecutableIds = useMemo((): Map<ExecutableType, Set<string>> | null => {
    if (!currentProject) return null;
    const map = new Map<ExecutableType, Set<string>>();
    if (!projectExecutables) {
      // While the GET is in flight, expose empty sets so the call sites that
      // filter on the project are empty (a project with no data shown is
      // safer than showing everything before the cache resolves).
      for (const t of ['script', 'testcase', 'virtual_script', 'campaign'] as ExecutableType[]) {
        map.set(t, new Set<string>());
      }
      return map;
    }
    map.set('script', new Set(projectExecutables.scripts.map((e) => e.id)));
    map.set('testcase', new Set(projectExecutables.testcases.map((e) => e.id)));
    map.set('virtual_script', new Set(projectExecutables.virtual_scripts.map((e) => e.id)));
    map.set('campaign', new Set(projectExecutables.campaigns.map((e) => e.id)));
    return map;
  }, [currentProject, projectExecutables]);

  // The name-set the legacy `isScriptAllowed(name)` checks against. Built
  // from the projectExecutables cache (all four lists' names unioned). Empty
  // when no project is selected — the legacy path returns the same as before.
  const projectNameSet = useMemo((): Set<string> | null => {
    if (!currentProject) return null;
    if (!projectExecutables) return new Set<string>(); // still loading = empty
    const s = new Set<string>();
    const add = (item: { id: string; name: string }) => {
      s.add(item.name);
      s.add(item.id);
      // scripts: also include the `.py` form so the legacy path keeps working
      // for callers that pass `name` from disk (which is bare) and from
      // /server/executable/list (which appends `.py`).
      s.add(`${item.name}.py`);
    };
    projectExecutables.scripts.forEach(add);
    projectExecutables.testcases.forEach(add);
    projectExecutables.virtual_scripts.forEach(add);
    projectExecutables.campaigns.forEach(add);
    return s;
  }, [currentProject, projectExecutables]);

  const isDeviceAllowed = useCallback(
    (hostName: string, deviceId: string): boolean => {
      const key = `${hostName}:${deviceId}`;
      if (effectiveDevices && !effectiveDevices.includes(key)) return false;
      if (!activeWorkspace) return true;
      if (!(activeWorkspace.device_filter ?? []).includes(key)) return false;
      // G9 project intersection: when a project is selected, the device's
      // `device_flags.flags` must share at least one tag name with the
      // project. `projectDeviceKeys` is null when no project is selected,
      // which means "no project scope" and we pass through.
      if (projectDeviceKeys !== null) {
        if (!projectDeviceKeys.has(key)) return false;
      }
      return true;
    },
    [activeWorkspace, effectiveDevices, projectDeviceKeys],
  );

  const deviceFilter = useMemo((): string[] | null => {
    const workspaceFilter = activeWorkspace ? activeWorkspace.device_filter ?? [] : null;
    // Resolve the project filter (or null = no scope) once.
    let projectFilter: string[] | null;
    if (projectDeviceKeys === null) {
      projectFilter = null;
    } else {
      projectFilter = Array.from(projectDeviceKeys);
    }
    // Three-way intersection. When the user has no scope at all, return the
    // least-restrictive signal (null). When any of the three is non-null, the
    // intersection is the literal set of keys that pass every check.
    const parts: Array<string[] | null> = [workspaceFilter, projectFilter, effectiveDevices];
    const nonNull = parts.filter((p): p is string[] => p !== null);
    if (nonNull.length === 0) return null;
    // Start with the first non-null list, then intersect with every other.
    let acc: Set<string> = new Set(nonNull[0]);
    for (let i = 1; i < nonNull.length; i++) {
      const next = new Set<string>();
      for (const k of acc) if ((nonNull[i] as string[]).includes(k)) next.add(k);
      acc = next;
    }
    return Array.from(acc);
  }, [activeWorkspace, effectiveDevices, projectDeviceKeys]);

  const isScriptAllowed = useCallback(
    (scriptName: string): boolean => {
      if (!activeWorkspace) return true;
      const filter = activeWorkspace.script_filter ?? [];
      // Normalize — /server/script/list returns bare names, /server/executable/list
      // returns names with .py. Accept either form in either direction.
      const withoutPy = scriptName.endsWith('.py') ? scriptName.slice(0, -3) : scriptName;
      const withPy = scriptName.endsWith('.py') ? scriptName : `${scriptName}.py`;
      const inWorkspace = filter.includes(scriptName) || filter.includes(withoutPy) || filter.includes(withPy);
      if (!inWorkspace) return false;
      // G9 project intersection: when a project is selected, the name (or its
      // .py variant) must resolve to an executable in the project's tagged
      // set. `projectNameSet` is null when no project is selected (pass
      // through); empty when the project has no tagged executables yet
      // (deny). Use the bare name OR the .py form so callers from both list
      // endpoints keep working.
      if (projectNameSet !== null) {
        if (
          !projectNameSet.has(scriptName) &&
          !projectNameSet.has(withoutPy) &&
          !projectNameSet.has(withPy)
        ) {
          return false;
        }
      }
      return true;
    },
    [activeWorkspace, projectNameSet],
  );

  // The G9 entry point from TASK-65 §14.2. True when the executable passes
  // the active workspace's rules AND the project intersection.
  const isExecutableAllowed = useCallback(
    (executableType: ExecutableType, executableId: string): boolean => {
      // Workspace scope: scripts and testcases are filtered by name; campaigns
      // and virtual scripts bypass the script_filter (the workspace's
      // `script_filter` is a name list for disk scripts only). To stay
      // consistent with `isScriptAllowed`, the workspace check here is
      // opt-in per type — only `script` rows are filtered by name.
      if (activeWorkspace && executableType === 'script') {
        const filter = activeWorkspace.script_filter ?? [];
        if (filter.length > 0) {
          // The script_filter carries the bare name; the executable id we get
          // here is the same value the legacy path uses, so just check both
          // forms for symmetry.
          const withoutPy = executableId.endsWith('.py') ? executableId.slice(0, -3) : executableId;
          const withPy = executableId.endsWith('.py') ? executableId : `${executableId}.py`;
          if (!filter.includes(executableId) && !filter.includes(withoutPy) && !filter.includes(withPy)) {
            return false;
          }
        }
      }
      // G9 project intersection: when a project is selected, the executable
      // must be in the project's tagged set for that type. projectExecutableIds
      // is null when no project is selected (pass through).
      if (projectExecutableIds !== null) {
        const set = projectExecutableIds.get(executableType);
        if (!set || !set.has(executableId)) return false;
      }
      return true;
    },
    [activeWorkspace, projectExecutableIds],
  );

  // Hidden when the user lacks the page's permission (PAGE_PERMISSIONS), or the active
  // workspace hides it.
  const isPathHidden = useCallback(
    (path: string): boolean => {
      const needed = requiredPermissionForPath(path);
      if (needed && !canAccess(needed)) return true;
      if (!activeWorkspace) return false;
      return (activeWorkspace.hidden_pages ?? []).includes(path);
    },
    [activeWorkspace, canAccess],
  );

  // The script-name list that satisfies BOTH the active workspace's
  // `script_filter` AND the current project's tagged scripts (when a
  // project is selected). Returns `null` when no workspace AND no
  // project is active (caller treats that as "no script scope at all").
  // Used by `useDeployment` and `runManagementApi` to send a server-side
  // `script_filter` query parameter.
  const scriptFilter = useMemo((): string[] | null => {
    const workspaceFilter = activeWorkspace ? activeWorkspace.script_filter ?? [] : null;
    // projectNameSet is null when no project is selected; the script scope
    // is "every script in the workspace's filter" in that case.
    if (projectNameSet === null) return workspaceFilter;
    // Project scope: intersect the workspace's names with the project's
    // name set. The project set carries both bare and .py forms plus the
    // script ids, so a single Set membership check covers every variant.
    if (workspaceFilter === null) {
      // No workspace scope, but a project IS selected — return the project's
      // script names (so the server filters down to the project's scripts).
      return Array.from(projectNameSet);
    }
    return workspaceFilter.filter((n) => projectNameSet.has(n));
  }, [activeWorkspace, projectNameSet]);

  const value: WorkspaceContextValue = {
    userWorkspaces,
    activeWorkspace,
    setActiveWorkspace,
    isLoadingWorkspaces,
    isDeviceAllowed,
    deviceFilter,
    isScriptAllowed,
    isExecutableAllowed,
    projectExecutableIds,
    projectTagNames: tagNames,
    scriptFilter,
    isPathHidden,
  };

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
};

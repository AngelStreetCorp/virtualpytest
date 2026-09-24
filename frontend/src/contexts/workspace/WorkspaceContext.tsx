import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { useAuth } from '../../hooks/auth/useAuth';
import { useUserWorkspaces, usePublicWorkspaces, Workspace } from '../../hooks/pages/useWorkspaces';

const ACTIVE_WORKSPACE_KEY = 'vpt_active_workspace';

interface WorkspaceContextValue {
  userWorkspaces: Workspace[];
  activeWorkspace: Workspace | null;
  setActiveWorkspace: (id: string | null) => void;
  isLoadingWorkspaces: boolean;
  /**
   * True when the given `hostName:deviceId` target is allowed in the currently
   * active workspace. Returns true when no workspace is active. Stored keys
   * use the same format as `TargetPanel` (`hostName:deviceId`).
   */
  isDeviceAllowed: (hostName: string, deviceId: string) => boolean;
  /**
   * True when the given script is allowed in the active workspace.
   * Returns true when no workspace is active. Handles both bare names
   * (`goto_home`) and `.py`-suffixed names from /server/executable/list.
   */
  isScriptAllowed: (scriptName: string) => boolean;
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
  // GET /server/workspaces — which is @require_admin_role. An admin gets a 200
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

  const isDeviceAllowed = useCallback(
    (hostName: string, deviceId: string): boolean => {
      if (!activeWorkspace) return true;
      const filter = activeWorkspace.device_filter ?? [];
      return filter.includes(`${hostName}:${deviceId}`);
    },
    [activeWorkspace],
  );

  const isScriptAllowed = useCallback(
    (scriptName: string): boolean => {
      if (!activeWorkspace) return true;
      const filter = activeWorkspace.script_filter ?? [];
      // Normalize — /server/script/list returns bare names, /server/executable/list
      // returns names with .py. Accept either form in either direction.
      const withoutPy = scriptName.endsWith('.py') ? scriptName.slice(0, -3) : scriptName;
      const withPy = scriptName.endsWith('.py') ? scriptName : `${scriptName}.py`;
      return filter.includes(scriptName) || filter.includes(withoutPy) || filter.includes(withPy);
    },
    [activeWorkspace],
  );

  const isPathHidden = useCallback(
    (path: string): boolean => {
      if (!activeWorkspace) return false;
      return (activeWorkspace.hidden_pages ?? []).includes(path);
    },
    [activeWorkspace],
  );

  const value: WorkspaceContextValue = {
    userWorkspaces,
    activeWorkspace,
    setActiveWorkspace,
    isLoadingWorkspaces,
    isDeviceAllowed,
    isScriptAllowed,
    isPathHidden,
  };

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
};

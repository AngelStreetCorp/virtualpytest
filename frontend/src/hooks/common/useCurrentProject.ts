/**
 * useCurrentProject — TASK-65 G2 + G9
 *
 * The single source of truth for the active project in the top-bar
 * ProjectSelector. Mirrors `WorkspaceContext` but for projects:
 *
 *   * `projects`           every project the caller can see
 *   * `currentProject`     the one in `localStorage` (or null)
 *   * `setCurrentProject`  persist + notify subscribers
 *   * `isOnScopeAwarePage` true when the current page should be project-scoped
 *                          (Dashboard, Atlas, Heatmap, …). Used by the selector
 *                          to draw a gold border + tooltip when no project is
 *                          active.
 *   * `refresh()`          re-fetch the list (after a create / delete)
 *   * `tagNames`           the current project's tag names (G9). The
 *                          WorkspaceContext intersects them with each device's
 *                          `device_flags.flags` to scope the device list.
 *
 * The hook is intentionally framework-light: localStorage + a tiny
 * `useSyncExternalStore` store, plus a `useQuery` for the GET. Listeners
 * (ScopePicker) re-render on a `setCurrentProject` call.
 */
import { useCallback, useMemo, useSyncExternalStore } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocation } from 'react-router-dom';

import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { useI18n } from '../../i18n/useI18n';


const STORAGE_KEY = 'virtualpytest:project_id';


// Pages where the project selector matters for the visible data — see
// docs/tasks/TASK-65-projects.md §7 (page-by-page impact). Each is the
// exact `pathname` (no leading slash comparison issues; we strip trailing
// slashes for safety).
const SCOPE_AWARE_PATHS: ReadonlyArray<string> = [
  '/',                              // Dashboard
  '/agent-dashboard',
  '/monitoring/heatmap',
  '/monitoring/incidents',
  '/monitoring/analytics',
  '/test-results/reports',           // Test Reports
  '/test-results/quality',
  '/run/monitor',
  '/run/deployments',
  '/ai-agent',                      // Atlas / Agent Chat
  // Future (G3 / G4) — keep here so the selector already warns once they exist
  '/projects',
];


export interface Project {
  id: string;
  team_id: string;
  name: string;
  description?: string | null;
  color?: string | null;
  created_by?: string;
  created_at: string;
  updated_at: string;
  tags: Array<{ tag_id: number; name: string; color?: string; is_scope?: boolean }>;
  members: Array<{ team_member_id: string; role: 'owner' | 'viewer' }>;
  tag_ids: number[];
  member_count: number;
  owner_count: number;
  viewer_count: number;
  // G11 / BUG-0548 — the project's auto-created scope tag is mechanically
  // distinguished from user-attached tags via `projects_tags.is_scope` (see
  // migration 20261015b). These fields are optional so old backends keep
  // working; callers should fall back to `tag_ids.length` when they are
  // absent.
  scope_tag?: { tag_id: number; name: string; color?: string; is_scope?: true } | null;
  scope_tag_id?: number | null;
  user_tags?: Array<{ tag_id: number; name: string; color?: string }>;
  user_tag_ids?: number[];
  user_tag_count?: number;
}


export interface UseCurrentProjectResult {
  projects: Project[];
  currentProject: Project | null;
  setCurrentProject: (id: string | null) => void;
  isLoading: boolean;
  isOnScopeAwarePage: boolean;
  refresh: () => Promise<unknown>;
  /** Storage key — exposed for tests + the `/projects` page banner. */
  storageKey: string;
  /**
   * The lowercase tag names owned by the current project (the project's
   * tag(s) — the WorkspaceContext intersects them with `device_flags.flags`).
   * Empty array when no project is selected or the project has no tag yet.
   * Synced with the `currentProject.tags` from the list endpoint, so it's
   * reactive to the projects query.
   */
  tagNames: string[];
}

/**
 * The shape returned by `GET /server/projects/<id>/executables`. Kept in this
 * file (not a separate types module) because it's the G9 hook's output and
 * only G9 code consumes it.
 */
export interface ProjectExecutables {
  scripts: Array<{ id: string; name: string }>;
  testcases: Array<{ id: string; name: string }>;
  virtual_scripts: Array<{ id: string; name: string }>;
  campaigns: Array<{ id: string; name: string }>;
  tag_names: string[];
  project_id: string;
}

/**
 * Resolve the executables tagged with the current project. Returns
 * `null` when no project is selected, and an empty-bucket object when
 * the project has no tags yet (caller treats both as "nothing to scope").
 *
 * React-query caches the result keyed on the project id; the
 * WorkspaceContext invalidates the query on project change. G9 selectors
 * consume the cached value to filter their dropdowns / lists.
 */
export const useProjectExecutables = (
  projectId: string | null,
): {
  data: ProjectExecutables | null;
  isLoading: boolean;
  isFetched: boolean;
  error: unknown;
} => {
  const q = useQuery<ProjectExecutables | null>({
    queryKey: ['projects', 'executables', projectId],
    queryFn: async (): Promise<ProjectExecutables | null> => {
      if (!projectId) return null;
      const res = await api.get<ProjectExecutables>(
        buildServerUrl(`/server/projects/${projectId}/executables`),
      );
      return res ?? null;
    },
    enabled: !!projectId,
    // 30 s — the same staleness window as the project list. A rename in the
    // ProjectSelector picks up a new project id and the query refires.
    staleTime: 30_000,
  });
  return {
    data: q.data ?? null,
    isLoading: q.isLoading,
    isFetched: q.isFetched,
    error: q.error,
  };
};


// ---------- tiny store (localStorage + subscribers) ----------------------------

const read = (): string | null => {
  try { return window.localStorage.getItem(STORAGE_KEY); } catch { return null; }
};
const write = (id: string | null): void => {
  try {
    if (id === null) window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // storage blocked (private window, sandbox) — the choice just won't persist
  }
  emit();
};

let currentId: string | null = typeof window !== 'undefined' ? read() : null;
const listeners = new Set<() => void>();
const subscribe = (fn: () => void): (() => void) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};
const getSnapshot = (): string | null => currentId;
const emit = (): void => { for (const fn of listeners) fn(); };

const listenPublic = (_event: string, handler: (e: StorageEvent) => void): (() => void) => {
  window.addEventListener('storage', handler);
  return () => window.removeEventListener('storage', handler);
};

// Pick up another tab's choice (StorageEvent only fires on OTHER tabs, so
// same-tab updates still go through the listeners store above).
listenPublic('storage', (e: StorageEvent) => {
  if (e.key !== STORAGE_KEY) return;
  currentId = e.newValue;
  emit();
});


// ---------- hook --------------------------------------------------------------

export const useCurrentProject = (): UseCurrentProjectResult => {
  const queryClient = useQueryClient();
  const { pathname } = useLocation();
  // useI18n is imported for symmetry with other selector code; the only consumer
  // needing translations lives in ProjectSelector itself.
  useI18n();

  // localStorage-backed id, reactive across tabs.
  const storedId = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const { data, isLoading, refetch } = useQuery<Project[]>({
    queryKey: ['projects', 'list'],
    queryFn: async () => {
      const list = await api.get<Project[]>(buildServerUrl('/server/projects'));
      return Array.isArray(list) ? list : [];
    },
    // The selector renders before this resolves; a stale result is fine.
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  });

  const projects = data ?? [];
  const currentProject = useMemo(
    () => projects.find((p) => p.id === storedId) ?? null,
    [projects, storedId],
  );

  const setCurrentProject = useCallback((id: string | null): void => {
    currentId = id;
    write(id);
  }, []);

  const refresh = useCallback(async () => {
    return refetch();
  }, [refetch]);

  const isOnScopeAwarePage = useMemo(() => {
    const path = (pathname || '/').replace(/\/+$/, '') || '/';
    if (path === '/') return true; // Dashboard is scope-aware
    if (path.startsWith('/projects')) return true; // /projects, /projects/<id>
    return SCOPE_AWARE_PATHS.includes(path);
  }, [pathname]);

  // If the active project vanished (deleted), drop the storage entry so the
  // selector stops claiming it's still selected.
  if (storedId && projects.length > 0 && !currentProject && !isLoading) {
    // Defer to avoid setState-during-render; queue a microtask.
    queueMicrotask(() => {
      if (read() === storedId) write(null);
      queryClient.invalidateQueries({ queryKey: ['projects', 'list'] });
    });
  }

  return {
    projects,
    currentProject,
    setCurrentProject,
    isLoading,
    isOnScopeAwarePage,
    refresh,
    storageKey: STORAGE_KEY,
    // The current project's tag names, lowercased. Empty when no project
    // is selected OR the project has no tag yet (a freshly created project
    // before Atlas attached a tag, or a project the caller has no read
    // access to). The WorkspaceContext intersects this with the device's
    // `device_flags.flags` to scope the device list.
    tagNames: (currentProject?.tags || [])
      .map((t) => (t?.name || '').toString().toLowerCase())
      .filter((n) => n.length > 0),
  };
};


// ---------- direct accessors used outside React (page banners, etc.) ----------

export const readCurrentProjectId = (): string | null => read();

export const writeCurrentProjectId = (id: string | null): void => {
  currentId = id;
  write(id);
};
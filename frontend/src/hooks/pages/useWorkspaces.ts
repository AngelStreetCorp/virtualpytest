/**
 * Workspaces Hook
 *
 * Hook for managing workspaces with CRUD operations.
 * Follows the same patterns as useTeams.ts for consistency.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  description: string;
  permissions: string[];
  denied_permissions: string[];
  device_filter: string[];
  /**
   * Read-only labels for `device_filter`, resolved server-side from the live
   * host registry: `"host:device_id" -> device_name`. Keys whose host is
   * offline or owned by another backend_server are absent — fall back to the
   * raw key when a lookup misses. Never sent back on create/update.
   */
  device_filter_names?: Record<string, string>;
  script_filter: string[];
  project_tags: string[];
  hidden_pages: string[];
  is_public: boolean;
  member_count: number;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceMember {
  id: string;              // workspace_members.id
  type: 'user' | 'team';
  user_id?: string;
  full_name?: string;
  email?: string;
  team_id?: string;
  team_name?: string;
  role: string;
  created_at: string;
}

export interface WorkspaceCreatePayload {
  name: string;
  description?: string;
  permissions?: string[];
  denied_permissions?: string[];
  device_filter?: string[];
  script_filter?: string[];
  project_tags?: string[];
  hidden_pages?: string[];
  is_public?: boolean;
}

const workspacesUrl = (path: string = '') => buildServerUrl(`/server/workspaces${path}`);

// Query keys for React Query caching
const QUERY_KEYS = {
  workspaces: ['workspaces'],
  workspace: (id: string) => ['workspaces', id],
  workspaceMembers: (workspaceId: string) => ['workspaces', workspaceId, 'members'],
  userWorkspaces: (userId: string) => ['workspaces', 'user', userId],
};

/**
 * Hook for workspaces operations
 * Provides CRUD operations with React Query caching and state management
 */
export const useWorkspaces = () => {
  const queryClient = useQueryClient();

  // Fetch all workspaces
  const {
    data: workspaces = [],
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: QUERY_KEYS.workspaces,
    queryFn: async (): Promise<Workspace[]> => api.get(workspacesUrl()),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  // Invalidate every list that feeds the WorkspaceSwitcher in the header so
  // changes to `is_public`, `device_filter`, `hidden_pages`, membership, etc.
  // surface without a page refresh. Covers both the RPC-backed signed-in path
  // (['workspaces', 'user', userId]) and the anonymous public-only fallback
  // (['workspaces', 'public']).
  const invalidateDownstreamWorkspaceLists = () => {
    queryClient.invalidateQueries({ queryKey: ['workspaces', 'user'] });
    queryClient.invalidateQueries({ queryKey: ['workspaces', 'public'] });
  };

  // Create workspace mutation
  const createMutation = useMutation({
    mutationFn: async (payload: WorkspaceCreatePayload): Promise<Workspace> =>
      api.post(workspacesUrl(), payload),
    onSuccess: (newWorkspace) => {
      queryClient.setQueryData(QUERY_KEYS.workspaces, (old: Workspace[] = []) => [...old, newWorkspace]);
      invalidateDownstreamWorkspaceLists();
      console.log('[@hook:useWorkspaces:create] Successfully created and cached new workspace');
    },
    onError: (error) => {
      console.error('[@hook:useWorkspaces:create] Error creating workspace:', error);
    },
  });

  // Update workspace mutation
  const updateMutation = useMutation({
    mutationFn: async ({ id, payload }: { id: string; payload: WorkspaceCreatePayload }): Promise<Workspace> =>
      api.put(workspacesUrl(`/${id}`), payload),
    onSuccess: (updatedWorkspace, variables) => {
      queryClient.setQueryData(QUERY_KEYS.workspaces, (old: Workspace[] = []) =>
        old.map((ws) => (ws.id === variables.id ? updatedWorkspace : ws))
      );
      queryClient.setQueryData(QUERY_KEYS.workspace(variables.id), updatedWorkspace);
      invalidateDownstreamWorkspaceLists();
      console.log('[@hook:useWorkspaces:update] Successfully updated and cached workspace');
    },
    onError: (error) => {
      console.error('[@hook:useWorkspaces:update] Error updating workspace:', error);
    },
  });

  // Delete workspace mutation
  const deleteMutation = useMutation({
    mutationFn: async (id: string): Promise<void> => {
      await api.delete(workspacesUrl(`/${id}`));
    },
    onSuccess: (_, id) => {
      queryClient.setQueryData(QUERY_KEYS.workspaces, (old: Workspace[] = []) =>
        old.filter((ws) => ws.id !== id)
      );
      queryClient.removeQueries({ queryKey: QUERY_KEYS.workspace(id) });
      invalidateDownstreamWorkspaceLists();
      console.log('[@hook:useWorkspaces:delete] Successfully deleted and removed from cache');
    },
    onError: (error) => {
      console.error('[@hook:useWorkspaces:delete] Error deleting workspace:', error);
    },
  });

  // Add user to workspace mutation
  const addUserMutation = useMutation({
    mutationFn: async ({ workspaceId, userId, role }: { workspaceId: string; userId: string; role?: string }): Promise<WorkspaceMember> =>
      api.post(workspacesUrl(`/${workspaceId}/members/user`), { user_id: userId, role }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.workspaceMembers(variables.workspaceId) });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.workspaces });
      console.log('[@hook:useWorkspaces:addUser] Successfully added user to workspace');
    },
    onError: (error) => {
      console.error('[@hook:useWorkspaces:addUser] Error adding user to workspace:', error);
    },
  });

  // Add team to workspace mutation
  const addTeamMutation = useMutation({
    mutationFn: async ({ workspaceId, teamId, role }: { workspaceId: string; teamId: string; role?: string }): Promise<WorkspaceMember> =>
      api.post(workspacesUrl(`/${workspaceId}/members/team`), { team_id: teamId, role }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.workspaceMembers(variables.workspaceId) });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.workspaces });
      console.log('[@hook:useWorkspaces:addTeam] Successfully added team to workspace');
    },
    onError: (error) => {
      console.error('[@hook:useWorkspaces:addTeam] Error adding team to workspace:', error);
    },
  });

  // Remove member from workspace mutation
  const removeMemberMutation = useMutation({
    mutationFn: async ({ workspaceId, memberId }: { workspaceId: string; memberId: string }): Promise<void> => {
      await api.delete(workspacesUrl(`/${workspaceId}/members/${memberId}`));
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.workspaceMembers(variables.workspaceId) });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.workspaces });
      console.log('[@hook:useWorkspaces:removeMember] Successfully removed member from workspace');
    },
    onError: (error) => {
      console.error('[@hook:useWorkspaces:removeMember] Error removing member from workspace:', error);
    },
  });

  return {
    // Data
    workspaces,

    // Status
    isLoading,
    error: error instanceof Error ? error.message : null,

    // Actions
    refetch,
    createWorkspace: createMutation.mutateAsync,
    updateWorkspace: updateMutation.mutateAsync,
    deleteWorkspace: deleteMutation.mutateAsync,
    addWorkspaceUser: addUserMutation.mutateAsync,
    addWorkspaceTeam: addTeamMutation.mutateAsync,
    removeWorkspaceMember: removeMemberMutation.mutateAsync,

    // Mutation status
    isCreating: createMutation.isPending,
    isUpdating: updateMutation.isPending,
    isDeleting: deleteMutation.isPending,

    // Mutation errors
    createError: createMutation.error instanceof Error ? createMutation.error.message : null,
    updateError: updateMutation.error instanceof Error ? updateMutation.error.message : null,
    deleteError: deleteMutation.error instanceof Error ? deleteMutation.error.message : null,
  };
};

/**
 * Hook for getting a single workspace by ID
 */
export const useWorkspace = (id: string) => {
  return useQuery({
    queryKey: QUERY_KEYS.workspace(id),
    queryFn: async (): Promise<Workspace> => api.get(workspacesUrl(`/${id}`)),
    enabled: !!id,
    staleTime: 5 * 60 * 1000,
  });
};

/**
 * Hook for getting workspace members
 */
export const useWorkspaceMembers = (workspaceId: string) => {
  return useQuery({
    queryKey: QUERY_KEYS.workspaceMembers(workspaceId),
    queryFn: async (): Promise<WorkspaceMember[]> =>
      api.get(workspacesUrl(`/${workspaceId}/members`)),
    enabled: !!workspaceId,
    staleTime: 5 * 60 * 1000,
  });
};

/**
 * Hook for getting workspaces for a specific user
 */
export const useUserWorkspaces = (userId: string) => {
  return useQuery({
    queryKey: QUERY_KEYS.userWorkspaces(userId),
    queryFn: async (): Promise<Workspace[]> =>
      api.get(workspacesUrl(`/user/${userId}`)),
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });
};

/**
 * Hook for listing public workspaces only — used when there is no Supabase
 * session (no user id to query memberships with). Backed by the plain
 * GET /server/workspaces endpoint, filtered client-side to `is_public`.
 */
export const usePublicWorkspaces = (enabled: boolean) => {
  return useQuery({
    queryKey: ['workspaces', 'public'],
    queryFn: async (): Promise<Workspace[]> => {
      const all: Workspace[] = await api.get(workspacesUrl());
      return all.filter((w) => w.is_public);
    },
    enabled,
    staleTime: 5 * 60 * 1000,
  });
};

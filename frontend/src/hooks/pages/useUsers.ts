/**
 * Users Hook
 * 
 * Hook for managing users with CRUD operations.
 * Follows the same patterns as useDeviceModels.ts for consistency.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';

export interface User {
  id: string;
  full_name: string;
  email: string;
  avatar_url?: string;
  role: 'admin' | 'tester' | 'viewer';
  team_id?: string;
  team?: string;
  teams?: string[];
  permissions: string[];
  denied_permissions?: string[];
  created_at: string;
  updated_at: string;
}

export interface UserUpdatePayload {
  full_name?: string;
  avatar_url?: string;
  role?: 'admin' | 'tester' | 'viewer';
  team_id?: string;
  permissions?: string[];
  denied_permissions?: string[];
}

export interface AssignTeamPayload {
  team_id: string;
  team_role?: 'owner' | 'admin' | 'member';
}

// Base URL for list operations (no path ID needed)
const USERS_API_BASE_URL = buildServerUrl('/server/users');

// Build URL with ID in the path BEFORE query params are appended
const usersUrlWithId = (id: string) => buildServerUrl(`/server/users/${id}`);

// Query keys for React Query caching
const QUERY_KEYS = {
  users: ['users'],
  user: (id: string) => ['users', id],
};

/**
 * Hook for users operations
 * Provides CRUD operations with React Query caching and state management
 */
export const useUsers = () => {
  const queryClient = useQueryClient();

  // Fetch all users (admin only)
  const {
    data: users = [],
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: QUERY_KEYS.users,
    queryFn: async (): Promise<User[]> => api.get(USERS_API_BASE_URL),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  // Update user mutation
  const updateMutation = useMutation({
    mutationFn: async ({ id, payload }: { id: string; payload: UserUpdatePayload }): Promise<User> =>
      api.put(usersUrlWithId(id), payload),
    onSuccess: (updatedUser, variables) => {
      // Update the user in the cache
      queryClient.setQueryData(QUERY_KEYS.users, (old: User[] = []) =>
        old.map((user) => (user.id === variables.id ? updatedUser : user))
      );
      // Also update individual user cache if it exists
      queryClient.setQueryData(QUERY_KEYS.user(variables.id), updatedUser);
      console.log('[@hook:useUsers:update] Successfully updated and cached user');
    },
    onError: (error) => {
      console.error('[@hook:useUsers:update] Error updating user:', error);
    },
  });

  // Delete user mutation
  const deleteMutation = useMutation({
    mutationFn: async (id: string): Promise<void> => {
      await api.delete(usersUrlWithId(id));
    },
    onSuccess: (_, id) => {
      // Remove the user from the cache
      queryClient.setQueryData(QUERY_KEYS.users, (old: User[] = []) =>
        old.filter((user) => user.id !== id)
      );
      // Remove individual user cache
      queryClient.removeQueries({ queryKey: QUERY_KEYS.user(id) });
      console.log('[@hook:useUsers:delete] Successfully deleted and removed from cache');
    },
    onError: (error) => {
      console.error('[@hook:useUsers:delete] Error deleting user:', error);
    },
  });

  // Assign user to team mutation
  const assignTeamMutation = useMutation({
    mutationFn: async ({ userId, payload }: { userId: string; payload: AssignTeamPayload }): Promise<void> => {
      await api.post(buildServerUrl(`/server/users/${userId}/assign-team`), payload);
    },
    onSuccess: (_, { userId }) => {
      // Invalidate user queries to refetch updated data
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.users });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.user(userId) });
      console.log('[@hook:useUsers:assignTeam] Successfully assigned user to team');
    },
    onError: (error) => {
      console.error('[@hook:useUsers:assignTeam] Error assigning user to team:', error);
    },
  });

  return {
    // Data
    users,

    // Status
    isLoading,
    error: error instanceof Error ? error.message : null,

    // Actions
    refetch,
    updateUser: updateMutation.mutateAsync,
    deleteUser: deleteMutation.mutateAsync,
    assignUserToTeam: assignTeamMutation.mutateAsync,

    // Mutation status
    isUpdating: updateMutation.isPending,
    isDeleting: deleteMutation.isPending,
    isAssigningTeam: assignTeamMutation.isPending,

    // Mutation errors
    updateError: updateMutation.error instanceof Error ? updateMutation.error.message : null,
    deleteError: deleteMutation.error instanceof Error ? deleteMutation.error.message : null,
    assignTeamError: assignTeamMutation.error instanceof Error ? assignTeamMutation.error.message : null,
  };
};

/**
 * Hook for getting a single user by ID
 */
export const useUser = (id: string) => {
  return useQuery({
    queryKey: QUERY_KEYS.user(id),
    queryFn: async (): Promise<User> => api.get(usersUrlWithId(id)),
    enabled: !!id,
    staleTime: 5 * 60 * 1000,
  });
};


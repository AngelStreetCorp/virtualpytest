/**
 * Teams Hook
 * 
 * Hook for managing teams with CRUD operations.
 * Follows the same patterns as useDeviceModels.ts for consistency.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';

export interface Team {
  id: string;
  name: string;
  description: string;
  tenant_id: string;
  created_by?: string;
  is_default: boolean;
  member_count: number;
  created_at: string;
  updated_at: string;
}

export interface TeamCreatePayload {
  name: string;
  description?: string;
  is_default?: boolean;
  permissions?: string[];
}

export interface TeamMember {
  id: string;
  user_id: string;
  full_name: string;
  email: string;
  avatar_url?: string;
  role: string;
  team_role: string;
  created_at: string;
}

// Base URL for list/create (no path ID needed)
const TEAMS_API_BASE_URL = buildServerUrl('/server/teams');

// Build URL with ID in the path BEFORE query params are appended
const teamsUrlWithId = (id: string) => buildServerUrl(`/server/teams/${id}`);

// Query keys for React Query caching
const QUERY_KEYS = {
  teams: ['teams'],
  team: (id: string) => ['teams', id],
  teamMembers: (teamId: string) => ['teams', teamId, 'members'],
};

/**
 * Hook for teams operations
 * Provides CRUD operations with React Query caching and state management
 */
export const useTeams = () => {
  const queryClient = useQueryClient();

  // Fetch all teams
  const {
    data: teams = [],
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: QUERY_KEYS.teams,
    queryFn: async (): Promise<Team[]> => api.get(TEAMS_API_BASE_URL),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  // Create team mutation
  const createMutation = useMutation({
    mutationFn: async (payload: TeamCreatePayload): Promise<Team> =>
      api.post(TEAMS_API_BASE_URL, payload),
    onSuccess: (newTeam) => {
      // Add the new team to the cache
      queryClient.setQueryData(QUERY_KEYS.teams, (old: Team[] = []) => [...old, newTeam]);
      console.log('[@hook:useTeams:create] Successfully created and cached new team');
    },
    onError: (error) => {
      console.error('[@hook:useTeams:create] Error creating team:', error);
    },
  });

  // Update team mutation
  const updateMutation = useMutation({
    mutationFn: async ({ id, payload }: { id: string; payload: TeamCreatePayload }): Promise<Team> =>
      api.put(teamsUrlWithId(id), payload),
    onSuccess: (updatedTeam, variables) => {
      // Update the team in the cache
      queryClient.setQueryData(QUERY_KEYS.teams, (old: Team[] = []) =>
        old.map((team) => (team.id === variables.id ? updatedTeam : team))
      );
      // Also update individual team cache if it exists
      queryClient.setQueryData(QUERY_KEYS.team(variables.id), updatedTeam);
      console.log('[@hook:useTeams:update] Successfully updated and cached team');
    },
    onError: (error) => {
      console.error('[@hook:useTeams:update] Error updating team:', error);
    },
  });

  // Delete team mutation
  const deleteMutation = useMutation({
    mutationFn: async (id: string): Promise<void> => {
      await api.delete(teamsUrlWithId(id));
    },
    onSuccess: (_, id) => {
      // Remove the team from the cache
      queryClient.setQueryData(QUERY_KEYS.teams, (old: Team[] = []) =>
        old.filter((team) => team.id !== id)
      );
      // Remove individual team cache
      queryClient.removeQueries({ queryKey: QUERY_KEYS.team(id) });
      console.log('[@hook:useTeams:delete] Successfully deleted and removed from cache');
    },
    onError: (error) => {
      console.error('[@hook:useTeams:delete] Error deleting team:', error);
    },
  });

  return {
    // Data
    teams,

    // Status
    isLoading,
    error: error instanceof Error ? error.message : null,

    // Actions
    refetch,
    createTeam: createMutation.mutateAsync,
    updateTeam: updateMutation.mutateAsync,
    deleteTeam: deleteMutation.mutateAsync,

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
 * Hook for getting a single team by ID
 */
export const useTeam = (id: string) => {
  return useQuery({
    queryKey: QUERY_KEYS.team(id),
    queryFn: async (): Promise<Team> => api.get(teamsUrlWithId(id)),
    enabled: !!id,
    staleTime: 5 * 60 * 1000,
  });
};

/**
 * Hook for getting team members
 */
export const useTeamMembers = (teamId: string) => {
  return useQuery({
    queryKey: QUERY_KEYS.teamMembers(teamId),
    queryFn: async (): Promise<TeamMember[]> => api.get(buildServerUrl(`/server/teams/${teamId}/members`)),
    enabled: !!teamId,
    staleTime: 5 * 60 * 1000,
  });
};


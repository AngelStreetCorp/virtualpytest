/**
 * Roles Hook
 *
 * The role catalog (GET /server/roles): each role's default permissions (public.role_permissions),
 * preferred name, rank and device limit (public.roles). Edited on the
 * Roles page. Read by PermissionContext for every signed-in user.
 */

import { useCallback, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
import { Permission, Role, RoleDefaults, RoleInfo } from '../../types/auth';

const ROLES_QUERY_KEY = ['roles'];

interface RolesResponse {
  roles: RoleDefaults;
  catalog: RoleInfo[];
  admin_only_permissions: Permission[];
}

export interface RoleUpdate {
  role: Role;
  permissions?: Permission[];
  display_name?: string;
  allowed_devices?: string[] | null;
}

export const useRoles = ({ enabled = true }: { enabled?: boolean } = {}) => {
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ROLES_QUERY_KEY,
    queryFn: async (): Promise<RolesResponse> => api.get(buildServerUrl('/server/roles')),
    enabled,
    staleTime: 5 * 60 * 1000,
  });

  const updateMutation = useMutation({
    mutationFn: async ({ role, ...changes }: RoleUpdate) =>
      api.put(buildServerUrl(`/server/roles/${role}`), changes),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ROLES_QUERY_KEY }),
  });

  const catalog = useMemo(
    () => [...(data?.catalog ?? [])].sort((a, b) => a.rank - b.rank),
    [data],
  );
  const adminOnly = useMemo(() => new Set<Permission>(data?.admin_only_permissions ?? []), [data]);

  // The installation's name for a role; the id until the catalog has loaded.
  const roleLabel = useCallback(
    (role: string) => catalog.find((r) => r.role === role)?.display_name ?? role,
    [catalog],
  );
  // 0 = admin; unknown ranks below everything.
  const roleRank = useCallback(
    (role: string | null | undefined) => catalog.find((r) => r.role === role)?.rank ?? Number.MAX_SAFE_INTEGER,
    [catalog],
  );

  return {
    roles: data?.roles,
    catalog,
    adminOnly,
    roleLabel,
    roleRank,
    isLoading,
    error: error instanceof Error ? error.message : null,
    updateRole: updateMutation.mutateAsync,
    isUpdating: updateMutation.isPending,
    updateError: updateMutation.error instanceof Error ? updateMutation.error.message : null,
  };
};

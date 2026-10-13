import React, { createContext, useContext, useMemo } from 'react';
import { useAuthContext } from './AuthContext';
import { isAuthEnabled } from '../../lib/supabase';
import { Permission, Role, computeEffectivePermissions } from '../../types/auth';
import { useRoles } from '../../hooks/pages/useRoles';

interface PermissionContextType {
  role: Role | null;
  permissions: Permission[];
  // True while the caller's role defaults are still loading; gates must wait rather than deny.
  isLoading: boolean;
  hasRole: (requiredRole: Role | Role[]) => boolean;
  hasPermission: (permission: Permission) => boolean;
  canAccess: (permission: Permission | Permission[]) => boolean;
}

const PermissionContext = createContext<PermissionContextType | undefined>(undefined);

export const usePermissionContext = () => {
  const context = useContext(PermissionContext);
  if (!context) {
    throw new Error('usePermissionContext must be used within PermissionProvider');
  }
  return context;
};

interface PermissionProviderProps {
  children: React.ReactNode;
}

export const PermissionProvider: React.FC<PermissionProviderProps> = ({ children }) => {
  const { profile, isAuthenticated } = useAuthContext();

  // Role defaults come from the server (editable on the Roles page). Admin needs none.
  const needsRoleDefaults = isAuthEnabled && isAuthenticated && !!profile && profile.role !== 'admin';
  const { roles, isLoading: rolesLoading } = useRoles({ enabled: needsRoleDefaults });
  const isLoading = needsRoleDefaults && rolesLoading;

  // Effective permissions resolution:
  //   (role defaults ∪ profile.permissions − profile.denied_permissions) ∩ team ceiling
  const { role, permissions } = useMemo(() => {
    if (!isAuthenticated || !profile) {
      return { role: null, permissions: [] as Permission[] };
    }

    return {
      role: profile.role,
      permissions: computeEffectivePermissions(
        profile.role,
        roles?.[profile.role] || [],
        profile.team_ceiling ?? null,
        profile.permissions || [],
        profile.denied_permissions || [],
      ),
    };
  }, [profile, isAuthenticated, roles]);

  const hasRole = (requiredRole: Role | Role[]): boolean => {
    // OPEN_MODE: no auth configured platform-wide → everyone is effectively admin
    if (!isAuthEnabled) return true;
    if (!role) return false;
    return Array.isArray(requiredRole) ? requiredRole.includes(role) : role === requiredRole;
  };

  const hasPermission = (permission: Permission): boolean => {
    if (!isAuthEnabled) return true;
    if (!isAuthenticated) return false;
    return permissions.includes(permission);
  };

  const canAccess = (requirement: Permission | Permission[]): boolean => {
    if (!isAuthEnabled) return true;
    if (!isAuthenticated) return false;
    if (Array.isArray(requirement)) {
      return requirement.some((perm) => permissions.includes(perm));
    }
    return permissions.includes(requirement);
  };

  return (
    <PermissionContext.Provider value={{ role, permissions, isLoading, hasRole, hasPermission, canAccess }}>
      {children}
    </PermissionContext.Provider>
  );
};

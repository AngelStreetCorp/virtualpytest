import React, { createContext, useContext, useMemo } from 'react';
import { useAuthContext } from './AuthContext';
import { isAuthEnabled } from '../../lib/supabase';
import { Permission, Role, ROLE_PERMISSIONS, ADMIN_ALL_PERMISSIONS } from '../../types/auth';

interface PermissionContextType {
  role: Role | null;
  permissions: Permission[];
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

  // Effective permissions resolution:
  //   ROLE_DEFAULTS ∪ team_permissions ∪ profile.permissions − profile.denied_permissions
  const { role, permissions } = useMemo(() => {
    if (!isAuthenticated || !profile) {
      return { role: null, permissions: [] as Permission[] };
    }

    const userRole = profile.role;
    const rolePerms = ROLE_PERMISSIONS[userRole];

    // Admin gets all permissions (no denial override — admins always have full access)
    if (Array.isArray(rolePerms) && rolePerms.length === 1 && rolePerms[0] === '*') {
      return { role: userRole, permissions: ADMIN_ALL_PERMISSIONS };
    }

    const denied = new Set<Permission>(profile.denied_permissions || []);

    // Union: role defaults + team permissions + individual grants, minus denials
    const effective = new Set<Permission>();
    for (const p of rolePerms as Permission[]) {
      if (!denied.has(p)) effective.add(p);
    }
    for (const p of (profile.team_permissions || []) as Permission[]) {
      if (!denied.has(p)) effective.add(p);
    }
    for (const p of (profile.permissions || []) as Permission[]) {
      if (!denied.has(p)) effective.add(p);
    }

    return { role: userRole, permissions: Array.from(effective) };
  }, [profile, isAuthenticated]);

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
    <PermissionContext.Provider value={{ role, permissions, hasRole, hasPermission, canAccess }}>
      {children}
    </PermissionContext.Provider>
  );
};

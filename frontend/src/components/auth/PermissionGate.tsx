import React from 'react';
import { usePermissions } from '../../hooks/auth/usePermissions';
import { Permission, Role } from '../../types/auth';
import { isAuthEnabled } from '../../lib/supabase';

interface PermissionGateProps {
  children: React.ReactNode;
  requiredRole?: Role | Role[];
  requiredPermission?: Permission | Permission[];
  fallback?: React.ReactNode;
}

/**
 * Permission Gate Component
 * Conditionally renders children based on user permissions or role
 * 
 * @example
 * // Show component only to admins
 * <PermissionGate requiredRole="admin">
 *   <AdminSettings />
 * </PermissionGate>
 * 
 * @example
 * // Show component only if user has permission
 * <PermissionGate requiredPermission="delete_campaigns">
 *   <DeleteButton />
 * </PermissionGate>
 * 
 * @example
 * // Show fallback if no permission
 * <PermissionGate requiredPermission="api_testing" fallback={<UpgradePrompt />}>
 *   <ApiTestingPanel />
 * </PermissionGate>
 */
export const PermissionGate: React.FC<PermissionGateProps> = ({
  children,
  requiredRole,
  requiredPermission,
  fallback = null,
}) => {
  const { hasRole, canAccess } = usePermissions();

  // If auth is disabled, show everything
  if (!isAuthEnabled) {
    return <>{children}</>;
  }

  // Check role requirement
  if (requiredRole && !hasRole(requiredRole)) {
    return <>{fallback}</>;
  }

  // Check permission requirement
  if (requiredPermission && !canAccess(requiredPermission)) {
    return <>{fallback}</>;
  }

  return <>{children}</>;
};


import { usePermissionContext } from '../../contexts/auth/PermissionContext';

/**
 * Hook to access user permissions and roles
 * 
 * @returns {Object} Permission checking methods
 * @example
 * const { hasRole, canAccess } = usePermissions();
 * if (canAccess('api_testing')) { ... }
 */
export const usePermissions = () => {
  return usePermissionContext();
};




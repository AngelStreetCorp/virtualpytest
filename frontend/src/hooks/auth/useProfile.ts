import { useAuthContext } from '../../contexts/auth/AuthContext';

/**
 * Hook to access user profile data
 * 
 * @returns {Object} User profile and refresh method
 * @example
 * const { profile, refreshProfile } = useProfile();
 */
export const useProfile = () => {
  const { profile, refreshProfile } = useAuthContext();

  return {
    profile,
    refreshProfile,
    isAdmin: profile?.role === 'admin',
    isTester: profile?.role === 'tester',
    isViewer: profile?.role === 'viewer',
    // TASK-23: platform super admin. Stays distinct from isAdmin — regular
    // admins are unaware tenants exist; only this flag unlocks the Tenants UI.
    isPlatformAdmin: profile?.is_platform_admin === true,
  };
};




import { useAuthContext } from '../../contexts/auth/AuthContext';

/**
 * Hook to access authentication state and methods
 * 
 * @returns {Object} Auth state and methods
 * @example
 * const { user, isAuthenticated, signInWithGoogle, signOut } = useAuth();
 */
export const useAuth = () => {
  return useAuthContext();
};




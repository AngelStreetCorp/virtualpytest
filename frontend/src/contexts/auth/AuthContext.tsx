import React, { createContext, useContext, useEffect, useState } from 'react';
import { User, Session } from '@supabase/supabase-js';
import { supabase, signOutAllIdentities } from '../../lib/supabase';
import { clearServerIdentities } from '../../lib/serverIdentity';
import { UserProfile } from '../../types/auth';
import { clearAutoSignSession, tryActivateAutoSign } from '../../lib/autoSign';
import {
  profileCacheKey,
  pruneOrphanedProfileCacheKeys,
} from '../../config/cacheVersion';

interface AuthContextType {
  user: User | null;
  profile: UserProfile | null;
  session: Session | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  signInWithGoogle: () => Promise<void>;
  signInWithGithub: () => Promise<void>;
  signInWithEmail: (email: string, password: string) => Promise<void>;
  signUpWithEmail: (email: string, password: string, fullName?: string) => Promise<void>;
  resetPassword: (email: string) => Promise<void>;
  signOut: () => Promise<void>;
  refreshProfile: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuthContext = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuthContext must be used within AuthProvider');
  }
  return context;
};

interface AuthProviderProps {
  children: React.ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isAutoSigned, setIsAutoSigned] = useState(false);

  // Drop any cached profiles that were written by an older schema version.
  // Runs once per mount; cheap (one pass over keys with the same prefix).
  // Best-effort: a private-mode localStorage error throws is swallowed in
  // pruneOrphanedProfileCacheKeys().
  useEffect(() => {
    const removed = pruneOrphanedProfileCacheKeys();
    if (removed > 0 && typeof console !== 'undefined') {
      console.info(`[auth] pruned ${removed} orphaned profile cache key(s) (pre-version bump)`);
    }
  }, []);

  // Fetch user profile from database with caching
  const fetchProfile = async (userId: string): Promise<UserProfile | null> => {
    // Try cache first — keyed by userId AND a schema version constant so a
    // new field on UserProfile (e.g. is_platform_admin in TASK-23) auto-busts
    // the cache after deploy without operators having to clear localStorage.
    // See ../../config/cacheVersion.ts for the version-history rules.
    const cacheKey = profileCacheKey(userId);
    const cached = localStorage.getItem(cacheKey);
    if (cached) {
      try {
        const parsed = JSON.parse(cached);
        return parsed as UserProfile;
      } catch (e) {
        console.warn('Error parsing cached profile:', e);
        localStorage.removeItem(cacheKey);
      }
    }

    try {
      const { data, error } = await supabase
        .from('profiles')
        .select('*')
        .eq('id', userId)
        .single();

      if (error) {
        // Profile doesn't exist yet (common on first login before trigger runs)
        // or profiles table doesn't exist (SQL not run yet)
        console.warn('Profile fetch error (expected on first login):', error.message);
        return null;
      }

      if (!data) return null;

      // Fetch team permissions (union of all teams the user belongs to)
      const teamPermissions: string[] = [];
      try {
        const { data: memberships } = await supabase
          .from('team_members')
          .select('teams(permissions)')
          .eq('user_id', userId);
        if (memberships) {
          const seen = new Set<string>();
          for (const m of memberships) {
            const perms: string[] = (m as { teams?: { permissions?: string[] } }).teams?.permissions ?? [];
            for (const p of perms) {
              if (!seen.has(p)) { seen.add(p); teamPermissions.push(p); }
            }
          }
        }
      } catch {
        // Non-fatal — team permissions just won't be applied
      }

      const profile: UserProfile = {
        ...data,
        denied_permissions: data.denied_permissions ?? [],
        team_permissions: teamPermissions,
      } as UserProfile;

      // Update cache
      localStorage.setItem(cacheKey, JSON.stringify(profile));

      return profile;
    } catch (err) {
      console.warn('Error in fetchProfile (table may not exist yet):', err);
      return null;
    }
  };

  // Initialize auth state
  useEffect(() => {
    let mounted = true;
    let initialLoadHandled = false;

    const autoSigned = tryActivateAutoSign();
    if (autoSigned) {
      const now = new Date().toISOString();
      if (mounted) {
        setIsAutoSigned(true);
        setUser(null);
        setSession(null);
        setProfile({
          id: 'auto_signed',
          email: null,
          full_name: 'Auto Signed',
          avatar_url: null,
          role: 'admin',
          permissions: [],
          denied_permissions: [],
          team_permissions: [],
          created_at: now,
          updated_at: now,
        });
        setIsLoading(false);
      }
      return () => {
        mounted = false;
      };
    }

    // Safety timeout - clear loading if auth completely fails
    const timeout = setTimeout(() => {
      if (mounted && isLoading && !initialLoadHandled) {
        console.warn('[@AuthContext] Auth initialization timeout - clearing loading state');
        setIsLoading(false);
      }
    }, 3000); // 3 second timeout as fallback

    const initAuth = async () => {
      try {
        console.log('[@AuthContext] Initializing auth...');
        
        // Try to get session from localStorage immediately (synchronous-like speed)
        const { data: { session: initialSession }, error: sessionError } = await supabase.auth.getSession();
        
        if (sessionError) {
          console.error('[@AuthContext] Session error:', sessionError);
          if (mounted) {
            setIsLoading(false);
            initialLoadHandled = true;
            clearTimeout(timeout);
          }
          return;
        }
        
        if (mounted && initialSession) {
          console.log('[@AuthContext] Session found immediately:', initialSession.user.email);
          setSession(initialSession);
          setUser(initialSession.user);
          
          // Fetch profile before clearing loading state to ensure permissions are ready
          console.log('[@AuthContext] Fetching profile...');
          const userProfile = await fetchProfile(initialSession.user.id);
          
          if (mounted) {
            if (userProfile) {
              console.log('[@AuthContext] Profile loaded:', userProfile.role);
            }
            setProfile(userProfile);
            
            // Clear loading only after profile is fetched
            setIsLoading(false);
            initialLoadHandled = true;
            clearTimeout(timeout);
          }
        } else if (mounted) {
           // No session found immediately - clear loading and let user see login
           console.log('[@AuthContext] No immediate session found');
           setIsLoading(false);
           initialLoadHandled = true;
           clearTimeout(timeout);
        }
      } catch (error: any) {
        console.error('[@AuthContext] Error initializing auth:', error.message);
        if (mounted) {
          setIsLoading(false);
          initialLoadHandled = true;
          clearTimeout(timeout);
        }
      }
    };

    initAuth();

    // Listen for auth changes (login, logout, token refresh)
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      async (event, newSession) => {
        console.log('[@AuthContext] Auth state changed:', event, newSession ? `User: ${newSession.user.email}` : 'No session');
        
        if (!mounted) return;

        // Skip SIGNED_IN event on initial load (already handled by initAuth)
        if (event === 'SIGNED_IN' && !initialLoadHandled) {
          console.log('[@AuthContext] Skipping SIGNED_IN event - already handled by initAuth');
          return;
        }

        setSession(newSession);
        setUser(newSession?.user ?? null);

        if (newSession?.user) {
          const userProfile = await fetchProfile(newSession.user.id);
          if (mounted && userProfile) {
            console.log('[@AuthContext] Profile updated:', userProfile.role);
            setProfile(userProfile);
          }
        } else {
          setProfile(null);
        }

        if (!initialLoadHandled) {
          setIsLoading(false);
          initialLoadHandled = true;
          clearTimeout(timeout);
        }
      }
    );

    return () => {
      mounted = false;
      clearTimeout(timeout);
      subscription.unsubscribe();
    };
  }, []);

  // Sign in with Google
  const signInWithGoogle = async () => {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
      },
    });

    if (error) {
      console.error('Error signing in with Google:', error);
      throw error;
    }
  };

  // Sign in with GitHub
  const signInWithGithub = async () => {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'github',
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
      },
    });

    if (error) {
      console.error('Error signing in with GitHub:', error);
      throw error;
    }
  };

  // Sign in with Email/Password
  const signInWithEmail = async (email: string, password: string) => {
    const { error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (error) {
      console.error('Error signing in with email:', error);
      throw error;
    }
  };

  // Sign up with Email/Password
  const signUpWithEmail = async (email: string, password: string, fullName?: string) => {
    const { error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: {
          full_name: fullName,
        },
        // Supabase otherwise falls back to the project-wide Site URL, which
        // may point at a different deployment (for example www.virtualpytest.com).
        // Keep confirmation on the frontend where signup was initiated.
        emailRedirectTo: `${window.location.origin}/auth/callback`,
      },
    });

    if (error) {
      console.error('Error signing up with email:', error);
      throw error;
    }
  };

  // Reset Password
  const resetPassword = async (email: string) => {
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/auth/reset-password`,
    });

    if (error) {
      console.error('Error resetting password:', error);
      throw error;
    }
  };

  // Sign out
  const signOut = async () => {
    if (isAutoSigned) {
      clearAutoSignSession();
      setIsAutoSigned(false);
      setUser(null);
      setProfile(null);
      setSession(null);
      return;
    }
    // Sign out of EVERY server identity, not just the primary one (TASK-18). The user
    // may hold sessions for several Supabase instances via the server picker, and one
    // visible "sign out" must not leave any of them live.
    await signOutAllIdentities();

    const { error } = await supabase.auth.signOut();
    if (error) {
      console.error('Error signing out:', error);
      throw error;
    }
    // Drop the cached server→identity map so the next user re-probes instead of
    // inheriting this one's view of the fleet.
    clearServerIdentities();
    // Clear local storage cache
    if (user) {
      localStorage.removeItem(profileCacheKey(user.id));
    }
    setUser(null);
    setProfile(null);
    setSession(null);
  };

  // Refresh profile manually (bypassing cache read, but updating it)
  const refreshProfile = async () => {
    if (user) {
      try {
        const { data } = await supabase
          .from('profiles')
          .select('*')
          .eq('id', user.id)
          .single();

        if (data) {
          const refreshed: UserProfile = {
            ...data,
            denied_permissions: data.denied_permissions ?? [],
            team_permissions: [],
          } as UserProfile;
          localStorage.setItem(profileCacheKey(user.id), JSON.stringify(refreshed));
          setProfile(refreshed);
        }
      } catch (err) {
        console.error('Error refreshing profile:', err);
      }
    }
  };

  const value: AuthContextType = {
    user,
    profile,
    session,
    isLoading,
    isAuthenticated: isAutoSigned || !!user,
    signInWithGoogle,
    signInWithGithub,
    signInWithEmail,
    signUpWithEmail,
    resetPassword,
    signOut,
    refreshProfile,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

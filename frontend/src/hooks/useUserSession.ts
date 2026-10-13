import { useState, useCallback } from 'react';
import { APP_CONFIG } from '../config/constants';
import { useAuthContext } from '../contexts/auth/AuthContext';

// Singleton browser session id, shared by every hook instance in this tab
let globalSessionId: string | null = null;
const BROWSER_SESSION_STORAGE_KEY = 'vpt_browser_session_id';

export const getBrowserSessionId = (): string => {
  if (globalSessionId) return globalSessionId;

  let sessionId = '';
  if (typeof window !== 'undefined') {
    sessionId = localStorage.getItem(BROWSER_SESSION_STORAGE_KEY) || '';
  }
  if (!sessionId) {
    const timestamp = Date.now();
    const random = Math.random().toString(36).substring(2, 8);
    sessionId = `browser-${timestamp}-${random}`;
    if (typeof window !== 'undefined') {
      localStorage.setItem(BROWSER_SESSION_STORAGE_KEY, sessionId);
    }
  }
  globalSessionId = sessionId;
  return sessionId;
};

/**
 * Shared User Session Hook - Consistent User Identification
 *
 * Provides unified user identification for device control and tree locking systems.
 * userId is the logged-in Supabase user; deployments without a login (open mode,
 * public key) fall back to APP_CONFIG.DEFAULT_USER_ID.
 */
export const useUserSession = () => {
  const { user } = useAuthContext();
  const userId = user?.id || APP_CONFIG.DEFAULT_USER_ID;
  const [sessionId] = useState(getBrowserSessionId);

  // Check if a lock belongs to our user
  const isOurLock = useCallback(
    (lockInfo: any): boolean => {
      if (!lockInfo) return false;

      const ownerUserId =
        lockInfo.owner_user_id || lockInfo.user_id || lockInfo.ownerUserId;
      const ownerSessionId =
        lockInfo.owner_session_id || lockInfo.session_id || lockInfo.lockedBy;

      return ownerUserId === userId || ownerSessionId === sessionId;
    },
    [userId, sessionId],
  );

  return {
    userId,
    sessionId,
    isOurLock,
  };
};

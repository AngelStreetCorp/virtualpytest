import { useState, useCallback } from 'react';
import { APP_CONFIG } from '../config/constants';

// Singleton session data to prevent multiple instances
let globalSessionData: { userId: string; sessionId: string } | null = null;
const BROWSER_SESSION_STORAGE_KEY = 'vpt_browser_session_id';

/**
 * Shared User Session Hook - Consistent User Identification
 *
 * Provides unified user identification for device control and tree locking systems.
 */
export const useUserSession = () => {
  // Use singleton pattern to ensure only one session is created
  const [sessionData] = useState(() => {
    if (globalSessionData) {
      return globalSessionData;
    }

    // Use hardcoded default user ID for demo mode (no browser-user fallback)
    let userId = APP_CONFIG.DEFAULT_USER_ID;

    // Try to get user ID from browser storage if available (optional enhancement)
    if (typeof window !== 'undefined') {
      const storedUser = localStorage.getItem('cached_user');
      if (storedUser) {
        try {
          const user = JSON.parse(storedUser);
          if (user.id && user.id !== 'browser-user') {
            userId = user.id;
          }
        } catch (e) {
          // Use default user ID
        }
      }
    }

    // Generate a stable session ID using the resolved userId
    let sessionId = '';
    if (typeof window !== 'undefined') {
      const storedSessionId = localStorage.getItem(BROWSER_SESSION_STORAGE_KEY);
      if (storedSessionId && storedSessionId.startsWith(`${userId}-`)) {
        sessionId = storedSessionId;
      }
    }

    if (!sessionId) {
      const timestamp = Date.now();
      const random = Math.random().toString(36).substring(2, 8);
      sessionId = `${userId}-${timestamp}-${random}`;
      if (typeof window !== 'undefined') {
        localStorage.setItem(BROWSER_SESSION_STORAGE_KEY, sessionId);
      }
    }

    // Store in singleton
    globalSessionData = {
      userId,
      sessionId,
    };

    return globalSessionData;
  });

  // Check if a lock belongs to our user
  const isOurLock = useCallback(
    (lockInfo: any): boolean => {
      if (!lockInfo) return false;

      const ownerUserId =
        lockInfo.owner_user_id || lockInfo.user_id || lockInfo.ownerUserId;
      const ownerSessionId =
        lockInfo.owner_session_id || lockInfo.session_id || lockInfo.lockedBy;

      return ownerUserId === sessionData.userId || ownerSessionId === sessionData.sessionId;
    },
    [sessionData.userId, sessionData.sessionId],
  );

  return {
    userId: sessionData.userId,
    sessionId: sessionData.sessionId,
    isOurLock,
  };
};

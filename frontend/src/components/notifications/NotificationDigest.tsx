import React, { useEffect, useRef } from 'react';

import { useHistoryLoaded, useNotifications } from '../../contexts/notificationStore';
import { useToastContext } from '../../contexts/ToastContext';
import { selectDigest } from './notificationDigestLogic';

/**
 * The 24 h digest (TASK-166).
 *
 * Once per browser session, the platform looks at the notification history of the last 24 hours:
 * three most recent errors if there are any, three most recent warnings if there are none. It is
 * a small plain-text pill in the top-right corner — one line, no icon, the colour says the
 * severity. Click the caret to see the three problems; click one to jump to its cause.
 *
 * This component decides *whether* the digest shows; the toast itself is raised by the toast
 * context (contract #43).
 */

/** This session already showed the digest (survives a reload of the same tab). */
const SEEN_KEY = 'virtualpytest:notification-digest-seen';
/** How often the digest looks at the history. */
const CHECK_MS = 3000;

const seenThisSession = (): boolean => {
  try {
    return Boolean(sessionStorage.getItem(SEEN_KEY));
  } catch {
    return false;
  }
};

const rememberThisSession = () => {
  try {
    sessionStorage.setItem(SEEN_KEY, String(Date.now()));
  } catch {
    /* storage blocked: the digest may come back on the next reload */
  }
};

/** Mounted once in the top bar. It never renders anything itself. */
export const NotificationDigest: React.FC = () => {
  const items = useNotifications();
  const loaded = useHistoryLoaded();
  const { showDigest } = useToastContext();
  const fired = useRef(false);
  // The latest history, read by the interval: a store change must not restart the clock.
  const itemsRef = useRef(items);
  itemsRef.current = items;

  useEffect(() => {
    if (!loaded || fired.current || seenThisSession()) return;
    const id = window.setInterval(() => {
      if (fired.current) {
        window.clearInterval(id);
        return;
      }
      const selection = selectDigest(itemsRef.current, Date.now());
      if (!selection) return; // nothing to say yet: stay armed and look again
      fired.current = true;
      window.clearInterval(id);
      rememberThisSession();
      showDigest(selection);
    }, CHECK_MS);
    return () => window.clearInterval(id);
  }, [loaded, showDigest]);

  return null;
};

export default NotificationDigest;

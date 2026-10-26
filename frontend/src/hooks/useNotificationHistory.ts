import { useEffect } from 'react';

import { APP_CONFIG } from '../config/constants';
import { notificationStore, markHistoryLoaded, registerNotificationSync, type NotificationItem, type ServerNotification } from '../contexts/notificationStore';
import { api, apiClientJson } from '../utils/apiClient';
import { buildServerUrl } from '../utils/buildUrlUtils';

/**
 * Notification history per account (TASK-145): the bell / page list follows the user across browsers.
 * The store renders from its localStorage cache at once and never waits for the network; this hook only
 * (1) reads the server list once and merges it, then (2) registers the write-through. Failures are silent:
 * the cache keeps working and the next load merges again.
 */
const BASE = '/server/notifications';
const q = `team_id=${encodeURIComponent(APP_CONFIG.DEFAULT_TEAM_ID)}`;
const team_id = APP_CONFIG.DEFAULT_TEAM_ID;

const quiet = (p: Promise<unknown>) => {
  p.catch((err) => console.debug('Notification history not synced:', err));
};

const wire = {
  upsert: (items: NotificationItem[]) =>
    quiet(api.post(buildServerUrl(BASE), { team_id, items: items.map(({ id, category, severity, message, to, scope, ts, read, resolved_at }) => ({ id, category, severity, message, to, scope, ts, read, resolved_at: resolved_at ?? null })) })),
  markRead: (id?: string) => quiet(apiClientJson(buildServerUrl(BASE), { method: 'PATCH', body: JSON.stringify({ team_id, id }) })),
  dismiss: (id?: string) => quiet(api.delete(buildServerUrl(`${BASE}?${q}${id ? `&id=${encodeURIComponent(id)}` : ''}`))),
  purge: (ids: string[]) => quiet(Promise.all(ids.map((id) => api.delete(buildServerUrl(`${BASE}?${q}&id=${encodeURIComponent(id)}`))))),
};

let started = false;

const start = async () => {
  if (started) return;
  started = true;
  try {
    const res = await api.get<{ rows?: ServerNotification[]; user_id?: string }>(buildServerUrl(`${BASE}?${q}`));
    if (!res.user_id) return;
    registerNotificationSync(wire);
    notificationStore.loadServer(res.user_id, res.rows ?? []);
  } catch (err) {
    started = false; // signed out or server down: the next mount tries again
    console.debug('Notification history not loaded:', err);
  } finally {
    // TASK-166: the 24 h digest counts the history, so it waits for this — whether the merge
    // worked or not. Without it the digest could fire on the local cache alone and be wrong.
    markHistoryLoaded();
  }
};

export const useNotificationHistory = () => {
  useEffect(() => {
    void start();
  }, []);
};

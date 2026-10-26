import { useCallback, useEffect, useSyncExternalStore } from 'react';

import { APP_CONFIG } from '../config/constants';
import { setNotificationPrefs, type NotificationCategory, type NotificationPrefRow, type PrefScopeType } from '../contexts/notificationStore';
import { api } from '../utils/apiClient';
import { buildServerUrl } from '../utils/buildUrlUtils';

/**
 * Notification preferences (TASK-145): per account, in the database, so they follow the user across browsers.
 * One module-level store: the bell loads it once for the whole app (the toast routing reads it through
 * `setNotificationPrefs`) and the Notifications page edits the same rows.
 */
const BASE = '/server/notification-prefs';

interface PrefsState {
  rows: NotificationPrefRow[];
  userId: string | undefined;
  isAdmin: boolean;
  loaded: boolean;
}

let state: PrefsState = { rows: [], userId: undefined, isAdmin: false, loaded: false };
let loading: Promise<void> | null = null;
const listeners = new Set<() => void>();

const publish = (next: PrefsState) => {
  state = next;
  setNotificationPrefs(next.rows, next.userId);
  listeners.forEach((l) => l());
};
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
};

const teamQuery = () => `team_id=${encodeURIComponent(APP_CONFIG.DEFAULT_TEAM_ID)}`;

const load = (force = false): Promise<void> => {
  if (state.loaded && !force) return Promise.resolve();
  if (loading) return loading;
  loading = api
    .get<{ rows?: NotificationPrefRow[]; user_id?: string; is_admin?: boolean }>(buildServerUrl(`${BASE}?${teamQuery()}`))
    .then((res) => publish({ rows: res.rows ?? [], userId: res.user_id, isAdmin: !!res.is_admin, loaded: true }))
    .catch((err) => console.error('Error loading notification preferences:', err))
    .finally(() => {
      loading = null;
    });
  return loading;
};

export interface PrefKey {
  scope_type: PrefScopeType;
  scope_id: string;
  category: NotificationCategory;
}

export const useNotificationPrefs = () => {
  const current = useSyncExternalStore(subscribe, () => state);
  useEffect(() => {
    void load();
  }, []);

  /** Create or replace one row. Throws when the server refuses (not admin, locked). */
  const save = useCallback(async (row: NotificationPrefRow) => {
    await api.put(buildServerUrl(BASE), { team_id: APP_CONFIG.DEFAULT_TEAM_ID, row });
    await load(true);
  }, []);

  /** Drop one row so the category inherits again. */
  const remove = useCallback(async (key: PrefKey) => {
    await api.delete(buildServerUrl(`${BASE}?${teamQuery()}&${new URLSearchParams({ ...key }).toString()}`));
    await load(true);
  }, []);

  return { ...current, save, remove };
};

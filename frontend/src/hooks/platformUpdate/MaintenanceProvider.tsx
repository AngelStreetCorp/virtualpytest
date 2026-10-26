import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useAuth } from '../auth/useAuth';
import { isAuthEnabled } from '../../lib/supabase';
import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { MaintenanceContext, type MaintenanceNotice, type MaintenanceWindow } from './useMaintenanceWindow';

const POLL_MS = 60_000;

/**
 * Fetches GET /server/platform-update/maintenance once and then every minute, for the whole app: the banner,
 * every device badge and the guards read this one copy (TASK-95 / TASK-97). Any logged-in user.
 */
export const MaintenanceProvider: React.FC<React.PropsWithChildren> = ({ children }) => {
  const { isAuthenticated } = useAuth();
  const enabled = !isAuthEnabled || isAuthenticated;
  const [windows, setWindows] = useState<MaintenanceWindow[]>([]);
  const [notice, setNotice] = useState<MaintenanceNotice | null>(null);

  const reload = useCallback(async () => {
    try {
      const response = await apiClient(buildServerUrl('/server/platform-update/maintenance'));
      if (!response.ok) return;
      const data = await response.json();
      setWindows(Array.isArray(data.windows) ? data.windows : []);
      setNotice(data.notice ?? null);
    } catch {
      // keep the last known state; the next poll retries
    }
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;
    void reload();
    const timer = window.setInterval(() => void reload(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [enabled, reload]);

  const value = useMemo(() => ({ windows, notice, reload }), [windows, notice, reload]);
  return <MaintenanceContext.Provider value={value}>{children}</MaintenanceContext.Provider>;
};

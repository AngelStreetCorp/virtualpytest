import { useCallback, useEffect, useState } from 'react';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';

/** The caller's Atlas memory (TASK-172), as `GET /server/agent/memory` returns it. */
export interface AtlasMemoryStatus {
  /** False when the server switched the memory off, or the login is shared (auto-sign, API key). */
  available: boolean;
  reason: '' | 'off' | 'no_user';
  enabled: boolean;
  retention_days: number;
  lookback_days: number;
  days: number;
  entries: number;
  /** How many times the memory answered within the retention. */
  recalls: number;
}

const URL = '/server/agent/memory';

/** One user's on-demand memory switch: used by the AI agent page and Settings → AI. */
export const useAtlasMemory = () => {
  const [status, setStatus] = useState<AtlasMemoryStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.get<{ success?: boolean } & AtlasMemoryStatus>(buildServerUrl(URL));
      if (data?.success) setStatus(data);
    } catch {
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const setEnabled = useCallback(async (enabled: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const data = await api.put<{ success?: boolean; error?: string } & AtlasMemoryStatus>(buildServerUrl(URL), { enabled });
      if (data?.success) setStatus(data);
      else setError(data?.error || 'failed');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const forget = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const data = await api.delete<{ success?: boolean; error?: string } & AtlasMemoryStatus>(buildServerUrl(URL));
      if (data?.success) setStatus(data);
      else setError(data?.error || 'failed');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  return { status, busy, error, refresh, setEnabled, forget };
};

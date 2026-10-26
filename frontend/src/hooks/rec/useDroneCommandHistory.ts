import { useCallback, useEffect, useRef, useState } from 'react';

import type { DroneCommand } from '../../components/drone/flightHistory';
import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';

const POLL_MS = 3000;

interface HistoryResponse {
  success?: boolean;
  commands?: DroneCommand[];
  flight?: number;
  log_path?: string | null;
  error?: string;
}

/**
 * The Tello controller's command history (every command sent, refused ones too), newest last. Polled while `enabled`
 * (the view is open): a driven flight shows up as it happens. The controller keeps the newest 500 in memory.
 */
export function useDroneCommandHistory(hostName: string | undefined, deviceId: string | undefined, enabled: boolean) {
  const [commands, setCommands] = useState<DroneCommand[]>([]);
  const [currentFlight, setCurrentFlight] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    if (!hostName || !deviceId) return;
    try {
      const res = await api.post<HistoryResponse>(buildServerUrl('/server/drone/tello/command_history'), {
        host_name: hostName,
        device_id: deviceId,
        limit: 500,
      });
      if (!mounted.current) return;
      if (res?.success === false) {
        setError(res.error ?? 'The host did not answer');
        return;
      }
      setCommands(res?.commands ?? []);
      setCurrentFlight(res?.flight ?? 0);
      setError(null);
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e.message : 'The host did not answer');
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [hostName, deviceId]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;
    setLoading(true);
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [enabled, refresh]);

  return { commands, currentFlight, loading, error, refresh };
}

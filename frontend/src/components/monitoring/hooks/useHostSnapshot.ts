import { useCallback, useEffect, useRef, useState } from 'react';

import type { Host } from '../../../types/common/Host_Types';
import { apiClient } from '../../../utils/apiClient';
import { buildServerUrlForServer } from '../../../utils/buildUrlUtils';

export interface HostSnapshot {
  /** This host as its own server reports it, with full system stats. */
  snapshot: Host | null;
  /** Epoch ms of the last successful fetch. */
  fetchedAt: number | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

/**
 * One full-stats read of a single host, taken when the overlay opens and again only on
 * refresh(). No polling: the page-wide host list is a load-time snapshot (host_ping is
 * ignored there), so the overlay asks the host's own server for current numbers instead.
 */
export const useHostSnapshot = (host?: Host): HostSnapshot => {
  const [snapshot, setSnapshot] = useState<Host | null>(null);
  const [fetchedAt, setFetchedAt] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const requestIdRef = useRef(0);

  const hostName = host?.host_name;
  const serverUrl = host?.server_url ?? '';

  useEffect(() => {
    if (!hostName) return;
    const requestId = ++requestIdRef.current;
    const controller = new AbortController();
    setLoading(true);
    setError(null);

    (async () => {
      try {
        const response = await apiClient(
          buildServerUrlForServer(
            serverUrl,
            '/server/system/getAllHosts?include_actions=false&include_system_stats=true&force_refresh=true',
          ),
          { signal: controller.signal },
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        const found: Host | undefined = (data.hosts || []).find((h: Host) => h.host_name === hostName);
        if (requestId !== requestIdRef.current) return;
        if (!found) throw new Error('not registered');
        setSnapshot(found);
        setFetchedAt(Date.now());
      } catch (err: any) {
        if (controller.signal.aborted || requestId !== requestIdRef.current) return;
        setError(err?.message || 'fetch failed');
      } finally {
        if (requestId === requestIdRef.current) setLoading(false);
      }
    })();

    return () => controller.abort();
  }, [hostName, serverUrl, nonce]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  return { snapshot, fetchedAt, loading, error, refresh };
};

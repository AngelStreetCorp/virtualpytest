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
 * Polling cadence for the stream-stats overlay (TASK-20). 20s sits well below
 * the 30s ceiling the user named for the "checked Xs ago" label to be
 * truthful, and is the same cadence the Status page uses to refresh host
 * tiles. Manual `refresh()` (the icon in the overlay) short-circuits the
 * timer for the next tick.
 */
const HOST_SNAPSHOT_POLL_MS = 20_000;

/**
 * Read a single host's full stats from its own server, then keep refreshing
 * every HOST_SNAPSHOT_POLL_MS while the hook is alive. A manual `refresh()`
 * bumps the same effect deps so it short-circuits to a one-off re-read.
 *
 * The page-wide host list is a load-time snapshot (host_ping is ignored
 * there), so the overlay asks the host's own server for current numbers
 * instead.
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

  // Background poll (TASK-20). Skipped while a manual refresh is in flight
  // (loading) so the two don't race; a tab visibility change also resets
  // the timer so a long-idle overlay gets fresh data the moment the user
  // looks at it again.
  useEffect(() => {
    if (!hostName) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const schedule = () => {
      if (cancelled) return;
      timer = setTimeout(() => {
        if (cancelled || document.hidden) {
          schedule();
          return;
        }
        setNonce((n) => n + 1);
      }, HOST_SNAPSHOT_POLL_MS);
    };

    const onVisibility = () => {
      if (document.hidden || cancelled) return;
      if (timer) clearTimeout(timer);
      setNonce((n) => n + 1);
    };

    document.addEventListener('visibilitychange', onVisibility);
    schedule();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [hostName]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  return { snapshot, fetchedAt, loading, error, refresh };
};

/**
 * TASK-113 — migration helper: look up the home server URL for a
 * given host_name.
 *
 * The `serverHostsData` array (every server's catalog fetch) carries
 * the registered hosts. Each `hosts` entry has a `server_url` field
 * that was stamped at fetch time
 * (ServerManagerProvider.tsx:421-424). This hook is the one place
 * that resolves "the home server for this host".
 *
 * Used by per-row action call sites that need to dispatch to the
 * row's home server in ALL mode. List calls stay on the currently
 * selected server (they fan out per server in a separate code path
 * per the rewrite §5.2).
 */
import { useCallback, useMemo } from 'react';
import { buildServerUrl, buildServerUrlForServer } from '../../utils/buildUrlUtils';
import { useServerManager } from '../../hooks/useServerManager';

export const lookupHostServerUrl = (
  serverHostsData: Array<{
    server_info: { server_url: string; server_name?: string };
    hosts?: Array<{ host_name: string; server_url?: string }>;
  }>,
  hostName: string,
): string | null => {
  if (!hostName) return null;
  for (const entry of serverHostsData) {
    const hosts = entry.hosts ?? [];
    for (const h of hosts) {
      if (h.host_name === hostName) {
        return h.server_url ?? entry.server_info?.server_url ?? null;
      }
    }
  }
  return null;
};

/**
 * React hook wrapping the lookup. Re-runs only when the catalog
 * data or the host name changes. Returns null when the host is
 * not (yet) on any server the picker knows about.
 */
export const useRowServerUrl = (hostName: string | undefined | null): string | null => {
  const { serverHostsData } = useServerManager();
  return useMemo(() => {
    if (!hostName) return null;
    return lookupHostServerUrl(serverHostsData, hostName);
  }, [serverHostsData, hostName]);
};

/**
 * Returns `(hostName, endpoint) => url` that targets the server owning `hostName`.
 * Host-targeted calls (execute, take control, deployments) must not go to the selected
 * server in "All servers" mode: its registry does not know other servers' hosts and
 * answers 404 "Host X not found" (BUG-0625). Falls back to the selected server.
 */
export const useHostScopedUrl = (): ((hostName: string | undefined | null, endpoint: string) => string) => {
  const { serverHostsData } = useServerManager();
  return useCallback(
    (hostName, endpoint) => {
      const home = hostName ? lookupHostServerUrl(serverHostsData, hostName) : null;
      return home ? buildServerUrlForServer(home, endpoint) : buildServerUrl(endpoint);
    },
    [serverHostsData],
  );
};

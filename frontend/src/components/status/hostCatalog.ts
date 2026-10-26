import type { Host } from '../../types/common/Host_Types';
import type { ServerHostData } from '../../types/common/Server_Types';

/**
 * One physical host, one row.
 *
 * A host can be registered on more than one backend server: host-clone-1 and
 * host-clone-2 are on the primary server AND on the QualiAI server, and both
 * catalogs report the same machine (same `host_name`, same `host_api_url`).
 * A page that flat-maps every server's catalog therefore listed those two
 * hosts twice and counted their services twice in the "Services healthy"
 * tile (BUG-0771).
 *
 * The servers arrive in configuration order, so the primary server comes
 * first and its record wins. A later catalog may still fill in what the
 * winner left empty: a catalog polled without `system_stats` carries none,
 * and the service list of a host is what the Status page renders.
 */
export const dedupeHostsByName = (serverHostsData: ServerHostData[]): Host[] => {
  const byName = new Map<string, Host>();

  for (const entry of serverHostsData ?? []) {
    for (const host of entry.hosts ?? []) {
      if (!host?.host_name) continue;
      const known = byName.get(host.host_name);
      if (!known) {
        byName.set(host.host_name, host);
        continue;
      }
      // Same host, another server's catalog: keep the first record, but let a
      // richer one fill the gap (stats the first catalog did not ask for).
      if (!known.system_stats && host.system_stats) {
        byName.set(host.host_name, { ...known, system_stats: host.system_stats });
      }
    }
  }

  return [...byName.values()];
};

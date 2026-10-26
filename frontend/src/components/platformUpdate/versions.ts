import { useMemo } from 'react';

import { useServerManager } from '../../hooks/useServerManager';
import type { UpdateRun } from '../../hooks/platformUpdate/usePlatformUpdateRun';

/** Some version files prefix the value with a "current:" label. */
export const formatDeployVersion = (version: string | null | undefined): string =>
  (version ?? '').replace(/^\s*current\s*:\s*/i, '').trim();

const hashOf = (version: string): string => {
  const parts = version.split('-');
  return parts.length >= 2 ? parts[parts.length - 1] : version;
};

export interface InstalledVersions {
  server: string;
  frontend: string;
  hosts: Record<string, string>;
}

/** What each machine runs now, from the server list already loaded for the whole app (no extra fetch). */
export const useInstalledVersions = (): InstalledVersions => {
  const { serverHostsData } = useServerManager();
  return useMemo(() => {
    const hosts: Record<string, string> = {};
    for (const s of serverHostsData) {
      for (const h of s.hosts) {
        if (!(h.host_name in hosts)) hosts[h.host_name] = formatDeployVersion(h.deployed_version);
      }
    }
    const embedded = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : '';
    return {
      server: formatDeployVersion(serverHostsData[0]?.server_info?.deployed_version),
      frontend: embedded && embedded !== 'unknown' ? formatDeployVersion(embedded) : '',
      hosts,
    };
  }, [serverHostsData]);
};

/** Machines whose version differs from the server's (both known). Entries are `machine -> version`. */
export const differingMachines = (v: InstalledVersions): Array<[string, string]> => {
  if (!v.server) return [];
  const out: Array<[string, string]> = [];
  const check = (name: string, version: string) => {
    if (version && hashOf(version) !== hashOf(v.server)) out.push([name, version]);
  };
  check('frontend', v.frontend);
  for (const [name, version] of Object.entries(v.hosts)) check(name, version);
  return out;
};

/**
 * The versions as they were before the deploy. The server captures them once, when the deploy (step 3) starts, and
 * keeps them in the run (`versions_before`), so the "from" survives the server restart, a reload and another browser.
 * Null until the deploy has started.
 */
export const versionsBeforeOf = (run: UpdateRun | null): InstalledVersions | null => {
  const raw = run?.steps[3]?.data?.versions_before as Partial<InstalledVersions> | undefined;
  if (!raw) return null;
  const hosts: Record<string, string> = {};
  for (const [name, version] of Object.entries(raw.hosts ?? {})) hosts[name] = formatDeployVersion(version);
  return { server: formatDeployVersion(raw.server), frontend: formatDeployVersion(raw.frontend), hosts };
};

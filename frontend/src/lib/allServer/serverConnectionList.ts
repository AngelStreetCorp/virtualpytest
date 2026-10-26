/**
 * TASK-113 — PR-B: derive the trusted `ServerConnection[]` from the
 * existing `ServerManagerContext` state.
 *
 * The list is built from `serverHostsData` (the catalog fetch result)
 * and `serverAuthStates` (TASK-18's per-server discovery). The picker
 * and the hosts-fetch already produce these; this helper is the
 * one place that turns them into the `ServerConnection` shape that
 * `queryScope` consumes.
 *
 * The output is the eligible set for ALL-mode fan-out. `needs-auth`
 * and `unknown` peers are filtered out at the source: a request
 * would 401 anyway, and the picker already gates the UI on them.
 */
import type { ServerConnection } from '../../types/allServer/AllServer_Types';
import type { ServerHostData } from '../../types/common/Server_Types';
import type { ServerAuthState } from '../serverIdentity';

/** Build the trusted `ServerConnection[]` from the manager's live state. */
export const buildServerConnectionList = (
  serverHostsData: ServerHostData[],
  serverAuthStates: Record<string, ServerAuthState>,
): ServerConnection[] => {
  const result: ServerConnection[] = [];
  for (const entry of serverHostsData) {
    const url = entry.server_info?.server_url;
    if (!url) continue;
    const authState = serverAuthStates[url] ?? 'unknown';
    // `needs-auth` and `unknown` are excluded: a fetch would 401, and the
    // picker surfaces the lock icon for `needs-auth` already.
    if (authState !== 'authenticated' && authState !== 'no-auth-required') {
      continue;
    }
    result.push({
      serverId: url,
      url,
      name: entry.server_info.server_name || url,
      authState,
    });
  }
  return result;
};

/**
 * The server scope an Atlas message carries (TASK-179 P4): what the picker says, as plain names.
 * Pure (no auth, no network) so it can be unit-tested.
 */
import { isAllServersSentinel } from './scope';
import type { ServerHostData } from '../../types/common/Server_Types';

export interface TurnScope {
  /** 'all' or the selected server's name; '' when the picker has no name for it (the server then acts as before). */
  server_scope: string;
  /** The server the selected host belongs to, when exactly one server has a host of that name. */
  selected_host_server: string;
}

export const buildTurnScope = (
  selectedServer: string,
  serverHostsData: ServerHostData[],
  selectedHostName: string,
): TurnScope => {
  const allMode = isAllServersSentinel(selectedServer);
  const selectedName = allMode
    ? ''
    : serverHostsData.find((entry) => entry.server_info.server_url === selectedServer)?.server_info.server_name || '';
  const owners = selectedHostName
    ? serverHostsData
        .filter((entry) => entry.hosts.some((host) => host.host_name === selectedHostName))
        .map((entry) => entry.server_info.server_name)
    : [];
  return {
    server_scope: allMode ? 'all' : selectedName,
    selected_host_server: owners.length === 1 ? owners[0] : '',
  };
};

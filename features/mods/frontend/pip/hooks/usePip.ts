import { useMemo } from 'react';

import { useWorkspaceContext } from '../../../../../frontend/src/contexts/workspace/WorkspaceContext';
import { useHostData } from '../../../../../frontend/src/hooks/useHostManager';
import { useModStore } from '../../../../../frontend/src/mods/core/hooks/useModStore';
import type { Device, Host } from '../../../../../frontend/src/types/common/Host_Types';
import { isPaused, remoteShown, selectDevice, toggleRemote } from '../actions';
import { pipStore } from '../data/store';
import type { PipSelection } from '../types';

/** PiP state plus the hosts/devices the workspace allows, and the chosen one resolved. */
export const usePip = () => {
  const state = useModStore(pipStore);
  const { getAllHosts } = useHostData();
  const { isDeviceAllowed } = useWorkspaceContext();

  const hosts = useMemo(
    () =>
      getAllHosts()
        .map((h) => ({ ...h, devices: (h.devices ?? []).filter((d) => isDeviceAllowed(h.host_name, d.device_id)) }))
        .filter((h) => h.devices.length > 0),
    [getAllHosts, isDeviceAllowed],
  );

  const { host, device } = useMemo((): { host: Host | null; device: Device | null } => {
    const sel = state.selection;
    const h = sel ? hosts.find((x) => x.host_name === sel.hostName) ?? null : null;
    return { host: h, device: h?.devices.find((d) => d.device_id === sel?.deviceId) ?? null };
  }, [hosts, state.selection]);

  return {
    state,
    hosts,
    host,
    device,
    paused: isPaused(state),
    showRemote: remoteShown(state),
    select: (selection: PipSelection | null) => pipStore.update((s) => selectDevice(s, selection)),
    toggleRemote: () => pipStore.update(toggleRemote),
  };
};

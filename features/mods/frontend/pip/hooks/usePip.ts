import { useCallback, useMemo } from 'react';

import { useWorkspaceContext } from '../../../../../frontend/src/contexts/workspace/WorkspaceContext';
import { useHostData } from '../../../../../frontend/src/hooks/useHostManager';
import { useModStore } from '../../../../../frontend/src/mods/core/hooks/useModStore';
import type { Device, Host } from '../../../../../frontend/src/types/common/Host_Types';
import { clampPosition, isPaused, remoteShown, selectDevice, setCollapsed, setPosition, toggleRemote } from '../actions';
import { pipStore } from '../data/store';
import type { PipPosition, PipSelection } from '../types';

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

  const setPos = useCallback(
    (next: PipPosition, rect: DOMRect, viewportW: number, viewportH: number) =>
      pipStore.update((s) => setPosition(s, next, rect, viewportW, viewportH)),
    [],
  );

  // Re-clamp a stored position that no longer fits (window was resized down after a drag).
  // The overlay calls this once per viewport resize so the panel cannot reopen clipped.
  const reclamp = useCallback((rect: DOMRect, viewportW: number, viewportH: number) => {
    const { position } = pipStore.get();
    if (!position) return;
    const safeRect = { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom };
    const clamped = clampPosition(position, safeRect, viewportW, viewportH);
    if (clamped.x !== position.x || clamped.y !== position.y) {
      pipStore.update((s) => ({ ...s, position: clamped }));
    }
  }, []);

  return {
    state,
    hosts,
    host,
    device,
    paused: isPaused(state),
    showRemote: remoteShown(state),
    select: (selection: PipSelection | null) => pipStore.update((s) => selectDevice(s, selection)),
    toggleRemote: () => pipStore.update(toggleRemote),
    setCollapsed: (collapsed: boolean) => pipStore.update((s) => setCollapsed(s, collapsed)),
    setPosition: setPos,
    reclampPosition: reclamp,
  };
};
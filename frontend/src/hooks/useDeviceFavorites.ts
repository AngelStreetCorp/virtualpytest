import { useCallback, useEffect, useMemo, useSyncExternalStore } from 'react';

import { APP_CONFIG } from '../config/constants';
import { api } from '../utils/apiClient';
import { buildServerUrl } from '../utils/buildUrlUtils';

/**
 * Per-user device favorites (TASK-99). A favorite is keyed by host AND device id: device ids
 * ("device1") collide across hosts and servers, so a device id alone never identifies one.
 *
 * One module-level store backs every picker: all pickers on screen share one fetch and a star
 * clicked in one shows at once in the others. Toggling is optimistic and rolls back on failure.
 */
export interface DeviceKey {
  host_name: string;
  device_id: string;
}

const keyOf = (host: string, deviceId: string) => `${host}\u0000${deviceId}`;
const BASE = '/server/device-favorites';

let favorites: ReadonlySet<string> = new Set();
let loadState: 'idle' | 'loading' | 'done' = 'idle';
const listeners = new Set<() => void>();

const publish = (next: ReadonlySet<string>) => {
  favorites = next;
  listeners.forEach((listener) => listener());
};
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

const load = async () => {
  if (loadState !== 'idle') return;
  loadState = 'loading';
  try {
    const res = await api.get<{ favorites?: DeviceKey[] }>(
      buildServerUrl(`${BASE}?team_id=${encodeURIComponent(APP_CONFIG.DEFAULT_TEAM_ID)}`),
    );
    publish(new Set((res.favorites || []).map((f) => keyOf(f.host_name, f.device_id))));
    loadState = 'done';
  } catch (err) {
    console.error('Error loading device favorites:', err);
    loadState = 'idle'; // the next picker that mounts retries
  }
};

export interface UseDeviceFavoritesReturn {
  isFavorite: (hostName: string, deviceId: string) => boolean;
  toggle: (hostName: string, deviceId: string) => Promise<boolean>;
  count: number;
  /** Every starred device, host and id (names live in the data that is shown next to them). */
  items: DeviceKey[];
}

export const useDeviceFavorites = (): UseDeviceFavoritesReturn => {
  const current = useSyncExternalStore(subscribe, () => favorites);
  useEffect(() => {
    void load();
  }, []);

  const isFavorite = useCallback(
    (hostName: string, deviceId: string) => current.has(keyOf(hostName, deviceId)),
    [current],
  );

  const toggle = useCallback(async (hostName: string, deviceId: string): Promise<boolean> => {
    const key = keyOf(hostName, deviceId);
    const wasFavorite = favorites.has(key);
    const withChange = (add: boolean) => {
      const next = new Set(favorites);
      if (add) next.add(key);
      else next.delete(key);
      return next;
    };
    publish(withChange(!wasFavorite));
    try {
      const payload = { team_id: APP_CONFIG.DEFAULT_TEAM_ID, host_name: hostName, device_id: deviceId };
      if (wasFavorite) {
        const query = new URLSearchParams(payload).toString();
        await api.delete(buildServerUrl(`${BASE}?${query}`));
      } else {
        await api.put(buildServerUrl(BASE), payload);
      }
      return true;
    } catch (err) {
      console.error('Error saving device favorite:', err);
      publish(withChange(wasFavorite));
      return false;
    }
  }, []);

  const items = useMemo<DeviceKey[]>(
    () => Array.from(current).map((k) => {
      const [host_name, device_id] = k.split('\u0000');
      return { host_name, device_id };
    }),
    [current],
  );

  return useMemo(() => ({ isFavorite, toggle, count: current.size, items }), [isFavorite, toggle, current, items]);
};

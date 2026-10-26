import { useCallback, useEffect, useMemo, useSyncExternalStore } from 'react';

import { APP_CONFIG } from '../config/constants';
import { api } from '../utils/apiClient';
import { buildServerUrl } from '../utils/buildUrlUtils';

/**
 * Per-user executable favorites (TASK-100): scripts, test cases, virtual scripts, campaigns.
 * A favorite is keyed by kind AND item id (CONTRACTS #35): a script file name, a test case uuid
 * and a campaign id live in separate namespaces.
 *
 * One module-level store backs every picker: all pickers on screen share one fetch and a star
 * clicked in one shows at once in the others. Toggling is optimistic and rolls back on failure.
 */
export type ExecutableKind = 'script' | 'testcase' | 'virtual_script' | 'campaign';

/** The kind of a listed executable. A campaign is told apart by the caller (it is listed as a script or test case). */
export const executableKind = (item: { type: 'script' | 'testcase'; is_virtual?: boolean }): ExecutableKind =>
  item.type === 'testcase' ? 'testcase' : item.is_virtual ? 'virtual_script' : 'script';

const keyOf = (kind: ExecutableKind, itemId: string) => `${kind}\u0000${itemId}`;
const BASE = '/server/executable-favorites';

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
    const res = await api.get<{ favorites?: Array<{ kind: ExecutableKind; item_id: string }> }>(
      buildServerUrl(`${BASE}?team_id=${encodeURIComponent(APP_CONFIG.DEFAULT_TEAM_ID)}`),
    );
    publish(new Set((res.favorites || []).map((f) => keyOf(f.kind, f.item_id))));
    loadState = 'done';
  } catch (err) {
    console.error('Error loading executable favorites:', err);
    loadState = 'idle'; // the next picker that mounts retries
  }
};

export interface UseExecutableFavoritesReturn {
  isFavorite: (kind: ExecutableKind, itemId: string) => boolean;
  toggle: (kind: ExecutableKind, itemId: string) => Promise<boolean>;
  count: number;
}

export const useExecutableFavorites = (): UseExecutableFavoritesReturn => {
  const current = useSyncExternalStore(subscribe, () => favorites);
  useEffect(() => {
    void load();
  }, []);

  const isFavorite = useCallback(
    (kind: ExecutableKind, itemId: string) => current.has(keyOf(kind, itemId)),
    [current],
  );

  const toggle = useCallback(async (kind: ExecutableKind, itemId: string): Promise<boolean> => {
    const key = keyOf(kind, itemId);
    const wasFavorite = favorites.has(key);
    const withChange = (add: boolean) => {
      const next = new Set(favorites);
      if (add) next.add(key);
      else next.delete(key);
      return next;
    };
    publish(withChange(!wasFavorite));
    try {
      const payload = { team_id: APP_CONFIG.DEFAULT_TEAM_ID, kind, item_id: itemId };
      if (wasFavorite) {
        const query = new URLSearchParams(payload).toString();
        await api.delete(buildServerUrl(`${BASE}?${query}`));
      } else {
        await api.put(buildServerUrl(BASE), payload);
      }
      return true;
    } catch (err) {
      console.error('Error saving executable favorite:', err);
      publish(withChange(wasFavorite));
      return false;
    }
  }, []);

  return useMemo(() => ({ isFavorite, toggle, count: current.size }), [isFavorite, toggle, current]);
};

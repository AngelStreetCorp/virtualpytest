import { useCallback, useEffect } from 'react';

import { DEFAULT_VIEW_ID, LAYOUT_VIEWS, findView } from '../../constants/deviceLayouts';
import { STORAGE_KEYS } from '../../config/constants';
import type { DeviceView, ViewId } from '../../types/pages/deviceLayout.types';
import { usePersistedState } from '../usePersistedState';

const isTyping = (el: EventTarget | null) =>
  el instanceof HTMLElement && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName));

/**
 * Device page view (TASK-75): Grid 12/24/48 or a fixed layout, remembered per browser.
 * Keys 1–9 pick the layouts in menu order when no field has focus.
 */
export const useDeviceView = (enableShortcuts: boolean) => {
  const [storedId, setStoredId] = usePersistedState<string>(`${STORAGE_KEYS.REC_FILTERS}_view`, DEFAULT_VIEW_ID);
  const view: DeviceView = findView(storedId) ?? findView(DEFAULT_VIEW_ID)!;

  const setView = useCallback((id: ViewId) => setStoredId(id), [setStoredId]);

  useEffect(() => {
    if (!enableShortcuts) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
      const index = Number(e.key) - 1;
      if (Number.isInteger(index) && index >= 0 && index < LAYOUT_VIEWS.length) setStoredId(LAYOUT_VIEWS[index].id);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [enableShortcuts, setStoredId]);

  return { view, setView };
};

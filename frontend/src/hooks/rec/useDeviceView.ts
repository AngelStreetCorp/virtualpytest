import { useCallback, useEffect, useMemo } from 'react';

import { STORAGE_KEYS } from '../../config/constants';
import {
  DEFAULT_CUSTOM_SHAPE,
  DEFAULT_VIEW_ID,
  customPageSize,
  devicePageLayouts,
  findView,
  sanitizeCustomShape,
} from '../../constants/deviceLayouts';
import type { DeviceView, ViewId } from '../../types/pages/deviceLayout.types';
import { usePersistedState } from '../usePersistedState';

const isTyping = (el: EventTarget | null) =>
  el instanceof HTMLElement && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName));

/**
 * Device page view: Grid 12/24, a custom columns × rows (at most 100 per page),
 * or a layout that fits the screen. Remembered per browser.
 * Keys 1–4 pick the layouts in menu order when no field has focus.
 */
export const useDeviceView = (enableShortcuts: boolean) => {
  const [storedId, setStoredId] = usePersistedState<string>(`${STORAGE_KEYS.REC_FILTERS}_view`, DEFAULT_VIEW_ID);
  const [storedShape, setStoredShape] = usePersistedState<{ cols: number; rows: number }>(
    `${STORAGE_KEYS.REC_FILTERS}_gridShape`,
    DEFAULT_CUSTOM_SHAPE,
  );
  const customShape = sanitizeCustomShape(storedShape);

  const view: DeviceView = useMemo(() => {
    const base = findView(storedId) ?? findView(DEFAULT_VIEW_ID)!;
    if (base.kind !== 'grid' || !base.custom) return base;
    const size = customPageSize(customShape.cols, customShape.rows)!;
    return { ...base, pageSize: size, glyph: { cols: customShape.cols, rows: customShape.rows } };
  }, [storedId, customShape.cols, customShape.rows]);

  const setView = useCallback((id: ViewId) => setStoredId(id), [setStoredId]);

  const setCustomShape = useCallback((cols: number, rows: number) => {
    if (customPageSize(cols, rows) === null) return;
    setStoredShape({ cols, rows });
    setStoredId('gridCustom');
  }, [setStoredId, setStoredShape]);

  useEffect(() => {
    if (!enableShortcuts) return undefined;
    const layouts = devicePageLayouts();
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
      const index = Number(e.key) - 1;
      if (Number.isInteger(index) && index >= 0 && index < layouts.length) setStoredId(layouts[index].id);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [enableShortcuts, setStoredId]);

  return { view, setView, customShape, setCustomShape };
};

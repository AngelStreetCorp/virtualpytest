import { useCallback, useMemo } from 'react';

import { STORAGE_KEYS } from '../../config/constants';
import { usePersistedState } from '../usePersistedState';

type OrderMap = Record<string, string[]>;

/**
 * Per-layout tile order (TASK-75). Devices the operator moved keep their place; any
 * other device follows in the filter order. Swaps and promotions are stored per view id.
 */
export const useLayoutOrder = <T,>(viewId: string, items: T[], keyOf: (item: T) => string) => {
  const [orders, setOrders] = usePersistedState<OrderMap>(`${STORAGE_KEYS.REC_FILTERS}_layoutOrder`, {});

  const ordered = useMemo(() => {
    const byKey = new Map(items.map((item) => [keyOf(item), item]));
    const saved = (orders[viewId] ?? []).filter((k) => byKey.has(k));
    const savedSet = new Set(saved);
    const rest = items.map(keyOf).filter((k) => !savedSet.has(k));
    return [...saved, ...rest].map((k) => byKey.get(k)!);
    // keyOf is a pure accessor; items/orders/viewId carry every change.
     
  }, [items, orders, viewId]);

  const swap = useCallback(
    (a: string, b: string) => {
      if (a === b) return;
      const keys = ordered.map(keyOf);
      const i = keys.indexOf(a);
      const j = keys.indexOf(b);
      if (i < 0 || j < 0) return;
      [keys[i], keys[j]] = [keys[j], keys[i]];
      setOrders((prev) => ({ ...prev, [viewId]: keys }));
    },
     
    [ordered, setOrders, viewId],
  );

  const reset = useCallback(() => {
    setOrders((prev) => {
      const next = { ...prev };
      delete next[viewId];
      return next;
    });
  }, [setOrders, viewId]);

  return { ordered, swap, reset };
};

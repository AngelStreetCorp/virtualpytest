import { useEffect, useMemo, useState } from 'react';

import { useWorkspaceContext } from '../../../../../frontend/src/contexts/workspace/WorkspaceContext';
import { pageOptions } from '../actions';
import type { PageOption } from '../types';

/**
 * The app's menu pages the user can see here, Dashboard first.
 *
 * navItems is loaded on demand, not imported: it reads the feature list at load time, and
 * this mod is part of that list (features.ts → mods routes → here → navItems → features.ts),
 * so a static import would read the list before it exists.
 */
export const usePageOptions = (): PageOption[] => {
  const { isPathHidden } = useWorkspaceContext();
  const [entries, setEntries] = useState<PageOption[]>([]);

  useEffect(() => {
    let cancelled = false;
    void import('../../../../../frontend/src/config/navItems').then(({ ALL_NAV_ITEMS, DASHBOARD_ITEM }) => {
      if (!cancelled) setEntries([{ label: DASHBOARD_ITEM.label, section: 'Top', path: DASHBOARD_ITEM.path }, ...ALL_NAV_ITEMS]);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return useMemo(() => pageOptions(entries, isPathHidden), [entries, isPathHidden]);
};

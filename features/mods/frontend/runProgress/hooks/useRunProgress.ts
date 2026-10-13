import { useEffect, useMemo } from 'react';

import { useModStore } from '../../../../../frontend/src/mods/core/hooks/useModStore';
import { hideBand, pruneRows, sortedRows, summarize } from '../actions';
import { PRUNE_INTERVAL_MS } from '../constants';
import { runProgressStore } from '../data/store';

export const useRunProgress = () => {
  const state = useModStore(runProgressStore);

  useEffect(() => {
    const id = window.setInterval(() => runProgressStore.update((s) => pruneRows(s, Date.now())), PRUNE_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, []);

  const rows = useMemo(() => sortedRows(state), [state]);
  const summary = useMemo(() => summarize(rows), [rows]);

  return {
    rows,
    summary,
    hidden: state.hidden,
    hide: () => runProgressStore.update(hideBand),
  };
};

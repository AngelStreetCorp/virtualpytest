/**
 * Search / time range / result filter over Last Executions rows (Run Tests + project page).
 * Search and time range apply first; the Passed / Failed counts are within that view.
 */
import { useEffect, useMemo, useState } from 'react';

import type { ExecutionHistoryRow } from '../../components/common/ExecutionHistoryTable';

export type HistoryRange = 'all' | '1h' | '24h' | '7d';
export type HistoryResultFilter = 'all' | 'success' | 'failure';

const HISTORY_RANGE_MS = { '1h': 3_600_000, '24h': 86_400_000, '7d': 604_800_000 } as const;

export const useExecutionHistoryFilters = (rows: ExecutionHistoryRow[]) => {
  // A long history is mostly passes, and the row someone is looking for is nearly always the failed one.
  const [resultFilter, setResultFilter] = useState<HistoryResultFilter>('all');
  const [search, setSearch] = useState('');
  const [range, setRange] = useState<HistoryRange>('all');

  const searchedRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const cutoff = range === 'all' ? 0 : Date.now() - HISTORY_RANGE_MS[range];
    return rows.filter((row) => {
      if (cutoff && !(row.startedAtMs && row.startedAtMs >= cutoff)) return false;
      if (!q) return true;
      return [row.scriptLabel, row.targetLabel, row.id].some((v) => v.toLowerCase().includes(q));
    });
  }, [rows, search, range]);

  const filteredRows = useMemo(
    () => (resultFilter === 'all'
      ? searchedRows
      // `resultSuccess` is null while a run is queued or still going; such a row belongs to
      // neither bucket, so a filtered view drops it rather than guessing which it will become.
      : searchedRows.filter((row) => row.resultSuccess === (resultFilter === 'success'))),
    [searchedRows, resultFilter],
  );
  const passedCount = searchedRows.filter((row) => row.resultSuccess === true).length;
  const failedCount = searchedRows.filter((row) => row.resultSuccess === false).length;
  const hasSuccessful = rows.some((row) => row.resultSuccess === true);
  const hasFailed = rows.some((row) => row.resultSuccess === false);

  useEffect(() => {
    if ((resultFilter === 'success' && !hasSuccessful) || (resultFilter === 'failure' && !hasFailed)) {
      setResultFilter('all');
    }
  }, [resultFilter, hasFailed, hasSuccessful]);

  return {
    search, setSearch, range, setRange, resultFilter, setResultFilter,
    searchedRows, filteredRows, passedCount, failedCount, hasSuccessful, hasFailed,
  };
};

export type ExecutionHistoryFilterState = ReturnType<typeof useExecutionHistoryFilters>;

/**
 * Not executed in window: currently runnable tests on this server with no eligible
 * execution inside the selected window. This is a window statement, not "never run".
 */

import { Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from '@mui/material';
import React from 'react';

import { ExportMenu } from '../components/reports/ExportMenu';
import { EmptyState } from '../components/reports/PageState';
import { QualityPageShell, useQualityWindow } from '../components/reports/QualityPageShell';
import { useQualityQuery } from '../hooks/reports/useRunManagement';
import { QUALITY_DEFAULT_WINDOW, type NotExecutedRow } from '../types/reports';

const rowKey = (row: NotExecutedRow) =>
  [row.script_name, row.script_type, row.userinterface_name, row.environment].join('|');

const NeverExecuted: React.FC = () => {
  const [windowDays, setWindowDays] = useQualityWindow(QUALITY_DEFAULT_WINDOW.notExecuted);
  const query = useQualityQuery('notExecuted', { windowDays });
  const data = query.data;
  const rows: NotExecutedRow[] = data?.rows ?? [];

  const buildExport = () => ({
    title: `Not executed in window (${windowDays} days)`,
    summary: [
      ['Window (days)', windowDays],
      ['Window start', data?.window_start ?? ''],
      ['Window end', data?.window_end ?? ''],
      ['Runnable tests compared', data?.runnable_total ?? ''],
      ['Tests not executed in window', data?.row_total ?? rows.length],
    ] as Array<[string, string | number]>,
    headers: ['Test', 'Type', 'UI', 'Environment'],
    rows: rows.map((row) => [row.script_name, row.script_type, row.userinterface_name, row.environment]),
  });

  return (
    <QualityPageShell
      title="Not executed in window"
      description="Tests that are currently runnable on this server and have no eligible execution inside the selected window. Tests that cannot run here are not listed. A test missing from the window may still have run before it."
      windowDays={windowDays}
      onWindowChange={setWindowDays}
      loading={query.isLoading}
      error={query.error}
      window={data}
      actions={<ExportMenu buildExport={buildExport} disabled={!rows.length} />}
    >
      {rows.length === 0 ? (
        <EmptyState message="Every runnable test was executed in this window." />
      ) : (
        <TableContainer component={Paper} variant="outlined" sx={{ maxWidth: '100%', overflowX: 'auto' }}>
          <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 640, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
<colgroup><col /><col style={{ width: 110 }} /><col style={{ width: 150 }} /><col style={{ width: 110 }} /></colgroup>
            <TableHead>
              <TableRow>
                <TableCell>Test</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>UI</TableCell>
                <TableCell>Environment</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={rowKey(row)}>
                  <TableCell sx={{ wordBreak: 'break-word' }}>{row.script_name}</TableCell>
                  <TableCell>{row.script_type ?? '—'}</TableCell>
                  <TableCell>{row.userinterface_name ?? '—'}</TableCell>
                  <TableCell>{row.environment ?? '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
      {data && data.row_total > rows.length && (
        <EmptyState message={`Showing ${rows.length} of ${data.row_total} tests.`} />
      )}
      {data && typeof data.runnable_total === 'number' && (
        <EmptyState
          message={`${data.row_total} of ${data.runnable_total} runnable tests had no execution in the last ${data.window_days} days. When a test last ran before the window is not reported.`}
        />
      )}
    </QualityPageShell>
  );
};

export default NeverExecuted;

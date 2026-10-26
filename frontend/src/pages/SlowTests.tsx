/**
 * Slow tests: p50 / p95 duration of successful finished attempts per comparable identity
 * (test + UI + environment + host/device) inside the selected window.
 */

import { Link, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from '@mui/material';
import React from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { ExportMenu } from '../components/reports/ExportMenu';
import { EmptyState } from '../components/reports/PageState';
import { QualityPageShell, identityLabel, useQualityWindow } from '../components/reports/QualityPageShell';
import { formatDurationMs } from '../components/reports/status';
import { useQualityQuery } from '../hooks/reports/useRunManagement';
import { QUALITY_DEFAULT_WINDOW, REPORT_ROUTES, type SlowRow } from '../types/reports';

const SlowTests: React.FC = () => {
  const [windowDays, setWindowDays] = useQualityWindow(QUALITY_DEFAULT_WINDOW.slow);
  const query = useQualityQuery('slow', { windowDays });
  const data = query.data;
  const rows: SlowRow[] = data?.rows ?? [];

  const buildExport = () => ({
    title: `Slow tests (${windowDays} days)`,
    summary: [
      ['Window (days)', windowDays],
      ['Window start', data?.window_start ?? ''],
      ['Window end', data?.window_end ?? ''],
      ['Eligible attempts', data?.sample_size ?? ''],
      ['Minimum attempts', data?.min_attempts ?? ''],
    ] as Array<[string, string | number]>,
    headers: ['Test', 'UI', 'Environment', 'Host', 'Device', 'p50 (ms)', 'p95 (ms)', 'Samples'],
    rows: rows.map((row) => [
      row.identity.script_name,
      row.identity.userinterface_name,
      row.identity.environment,
      row.identity.host_name,
      row.identity.device_name,
      row.p50_ms,
      row.p95_ms,
      row.sample_count,
    ]),
  });

  return (
    <QualityPageShell
      title="Slow tests"
      description="Median (p50) and 95th percentile (p95) duration of successful, finished attempts. Durations are only compared within the same test, UI, environment and host/device."
      windowDays={windowDays}
      onWindowChange={setWindowDays}
      loading={query.isLoading}
      error={query.error}
      window={data}
      actions={<ExportMenu buildExport={buildExport} disabled={!rows.length} />}
    >
      {rows.length === 0 ? (
        <EmptyState message="No test has enough successful attempts in this window to report a duration." />
      ) : (
        <TableContainer component={Paper} variant="outlined" sx={{ maxWidth: '100%', overflowX: 'auto' }}>
          {/* Same as the flaky table: the Test column needs its own width, or it
              collapses on a phone (BUG-0794). */}
          <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 950 }}>
            <colgroup>
              <col style={{ width: 220 }} /><col style={{ width: 150 }} /><col style={{ width: 100 }} /><col style={{ width: 140 }} />
              <col style={{ width: 80 }} /><col style={{ width: 80 }} /><col style={{ width: 80 }} /><col style={{ width: 100 }} />
            </colgroup>
            <TableHead>
              <TableRow>
                <TableCell>Test</TableCell>
                <TableCell>UI</TableCell>
                <TableCell>Environment</TableCell>
                <TableCell>Host / device</TableCell>
                <TableCell align="right">p50</TableCell>
                <TableCell align="right">p95</TableCell>
                <TableCell align="right">Samples</TableCell>
                <TableCell>Evidence</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={identityLabel(row.identity)}>
                  <TableCell sx={{ wordBreak: 'break-word' }}>{row.identity.script_name}</TableCell>
                  <TableCell sx={{ overflowWrap: 'anywhere' }}>{row.identity.userinterface_name ?? '—'}</TableCell>
                  <TableCell>{row.identity.environment ?? '—'}</TableCell>
                  <TableCell>
                    {row.identity.host_name ?? '—'} / {row.identity.device_name ?? '—'}
                  </TableCell>
                  <TableCell align="right">{formatDurationMs(row.p50_ms)}</TableCell>
                  <TableCell align="right">{formatDurationMs(row.p95_ms)}</TableCell>
                  <TableCell align="right">{row.sample_count}</TableCell>
                  <TableCell>
                    {row.latest_script_result_id ? (
                      <Link component={RouterLink} to={REPORT_ROUTES.summary('script', row.latest_script_result_id)}>
                        Latest run
                      </Link>
                    ) : (
                      '—'
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </QualityPageShell>
  );
};

export default SlowTests;

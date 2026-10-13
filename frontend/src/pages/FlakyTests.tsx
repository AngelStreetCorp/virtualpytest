/**
 * Flaky tests: adjacent pass/fail transitions per comparable identity
 * (test + UI + environment + host/device) inside the selected window.
 */

import { Link, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from '@mui/material';
import React from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { ExportMenu } from '../components/reports/ExportMenu';
import { EmptyState } from '../components/reports/PageState';
import { QualityPageShell, identityLabel, useQualityWindow } from '../components/reports/QualityPageShell';
import { STATUS_LABELS, StatusChip, formatDateTime } from '../components/reports/status';
import { useQualityQuery } from '../hooks/reports/useRunManagement';
import { QUALITY_DEFAULT_WINDOW, REPORT_ROUTES, type FlakyRow } from '../types/reports';

const formatScore = (score: number | null): string =>
  score === null ? '—' : `${Math.round(score * 1000) / 10}%`;

const FlakyTests: React.FC = () => {
  const [windowDays, setWindowDays] = useQualityWindow(QUALITY_DEFAULT_WINDOW.flaky);
  const query = useQualityQuery('flaky', { windowDays });
  const data = query.data;
  const rows: FlakyRow[] = data?.rows ?? [];

  const buildExport = () => ({
    title: `Flaky tests (${windowDays} days)`,
    summary: [
      ['Window (days)', windowDays],
      ['Window start', data?.window_start ?? ''],
      ['Window end', data?.window_end ?? ''],
      ['Eligible attempts', data?.sample_size ?? ''],
      ['Minimum attempts', data?.min_attempts ?? ''],
    ] as Array<[string, string | number]>,
    headers: ['Test', 'UI', 'Environment', 'Host', 'Device', 'Flaky score', 'Transitions', 'Attempts', 'Passes', 'Failures', 'Last status'],
    rows: rows.map((row) => [
      row.identity.script_name,
      row.identity.userinterface_name,
      row.identity.environment,
      row.identity.host_name,
      row.identity.device_name,
      formatScore(row.flaky_score),
      row.transitions,
      row.attempts,
      row.passes,
      row.failures,
      STATUS_LABELS[row.last_status],
    ]),
  });

  return (
    <QualityPageShell
      title="Flaky tests"
      description="Score = adjacent pass↔fail transitions ÷ (attempts − 1). Attempts are only compared within the same test, UI, environment and host/device — a difference between devices is never counted as flakiness. A score describes behaviour, not a root cause."
      windowDays={windowDays}
      onWindowChange={setWindowDays}
      loading={query.isLoading}
      error={query.error}
      window={data}
      actions={<ExportMenu buildExport={buildExport} disabled={!rows.length} />}
    >
      {rows.length === 0 ? (
        <EmptyState message="No test met the minimum attempts with both a pass and a failure in this window." />
      ) : (
        <TableContainer component={Paper} variant="outlined" sx={{ maxWidth: '100%', overflowX: 'auto' }}>
          <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 940 }}>
            <colgroup>
              <col /><col style={{ width: 150 }} /><col style={{ width: 100 }} /><col style={{ width: 140 }} />
              <col style={{ width: 70 }} /><col style={{ width: 100 }} /><col style={{ width: 80 }} />
              <col style={{ width: 100 }} /><col style={{ width: 130 }} /><col style={{ width: 100 }} />
            </colgroup>
            <TableHead>
              <TableRow>
                <TableCell>Test</TableCell>
                <TableCell>UI</TableCell>
                <TableCell>Environment</TableCell>
                <TableCell>Host / device</TableCell>
                <TableCell align="right">Score</TableCell>
                <TableCell align="right">Transitions</TableCell>
                <TableCell align="right">Attempts</TableCell>
                <TableCell align="right">Pass / fail</TableCell>
                <TableCell>Last</TableCell>
                <TableCell>Evidence</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={identityLabel(row.identity)} data-testid="flaky-row">
                  <TableCell sx={{ wordBreak: 'break-word' }}>{row.identity.script_name}</TableCell>
                  <TableCell sx={{ overflowWrap: 'anywhere' }}>{row.identity.userinterface_name ?? '—'}</TableCell>
                  <TableCell>{row.identity.environment ?? '—'}</TableCell>
                  <TableCell>
                    {row.identity.host_name ?? '—'} / {row.identity.device_name ?? '—'}
                  </TableCell>
                  <TableCell align="right">{formatScore(row.flaky_score)}</TableCell>
                  <TableCell align="right">
                    {row.transitions} / {Math.max(row.attempts - 1, 0)}
                  </TableCell>
                  <TableCell align="right">{row.attempts}</TableCell>
                  <TableCell align="right">
                    {row.passes} / {row.failures}
                  </TableCell>
                  <TableCell>
                    <StatusChip status={row.last_status} />
                    <br />
                    {formatDateTime(row.last_started_at)}
                  </TableCell>
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

export default FlakyTests;

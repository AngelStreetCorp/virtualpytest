/**
 * Public, read-only run snapshot.
 *
 * Opened by anonymous visitors: no workspace, permission or socket context, no links into
 * the app. The token arrives in the URL fragment (`#t=…`, never sent to a server by the
 * browser), is removed from the address bar immediately and travels only in a request
 * header. Only the allowlisted snapshot fields are rendered.
 */

import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

import { StatTile } from '../components/analytics/StatTile';
import { RunStatusDonut } from '../components/reports/RunCharts';
import { STATUS_COLORS, STATUS_LABELS, StatusChip, formatDateTime, formatDurationMs } from '../components/reports/status';
import { ExportMenu } from '../components/reports/ExportMenu';
import { fetchPublicShare, isApiError } from '../hooks/reports/runManagementApi';
import { RUN_STATUSES, type SharePayload } from '../types/reports';

/** Read `t` from the URL fragment (pure: safe for a useState initializer). */
const readTokenFromFragment = (): string | null => {
  const hash = window.location.hash;
  if (!hash || hash.length < 2) return null;
  const token = new URLSearchParams(hash.slice(1)).get('t');
  return token && token.trim() ? token.trim() : null;
};

/** Drop the fragment from the address bar so the token is not left in history or copied along. */
const stripFragment = () => {
  if (!window.location.hash) return;
  window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}`);
};

const DENIED_STATUSES = [401, 403, 404, 410];

/** Copy only the allowlisted fields, whatever else the response carried. */
const allowlisted = (payload: SharePayload): SharePayload => ({
  title: payload.title,
  status: payload.status,
  counts: payload.counts,
  durations: {
    started_at: payload.durations?.started_at ?? null,
    completed_at: payload.durations?.completed_at ?? null,
    execution_time_ms: payload.durations?.execution_time_ms ?? null,
  },
  safe_labels: (payload.safe_labels ?? []).filter((label) => typeof label === 'string'),
  rows: (payload.rows ?? []).map((row) => ({
    name: row.name,
    status: row.status,
    execution_time_ms: row.execution_time_ms ?? null,
  })),
  rows_truncated: payload.rows_truncated === true,
});

const Shell: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Box
    component="main"
    sx={{ width: '100%', maxWidth: 960, mx: 'auto', px: { xs: 2, sm: 3 }, py: 3, minWidth: 0, overflowX: 'hidden' }}
  >
    {children}
  </Box>
);

const ShareRun: React.FC = () => {
  const { snapshotId = '' } = useParams<{ snapshotId: string }>();
  const [token] = useState<string | null>(readTokenFromFragment);

  useEffect(() => {
    stripFragment();
  }, []);

  const query = useQuery({
    queryKey: ['public-share', snapshotId, token],
    queryFn: () => fetchPublicShare(snapshotId, token as string),
    enabled: Boolean(snapshotId && token),
    retry: false,
    staleTime: Infinity,
  });

  if (!token) {
    return (
      <Shell>
        <Alert severity="warning" data-testid="share-incomplete">
          This link is incomplete. Ask the person who shared it for the full link.
        </Alert>
      </Shell>
    );
  }

  if (query.isLoading) {
    return (
      <Shell>
        <Box role="status" aria-label="Loading" sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
          <CircularProgress size={28} />
        </Box>
      </Shell>
    );
  }

  if (query.isError || !query.data) {
    const denied = isApiError(query.error) && DENIED_STATUSES.includes(query.error.status);
    return (
      <Shell>
        <Alert severity={denied ? 'warning' : 'error'} data-testid={denied ? 'share-invalid' : 'share-error'}>
          {denied
            ? 'This link is invalid, expired or revoked.'
            : 'The snapshot could not be loaded right now. Try again later.'}
        </Alert>
      </Shell>
    );
  }

  const { snapshot } = query.data;
  const payload = allowlisted(snapshot.payload);

  const buildExport = () => ({
    title: payload.title,
    summary: [
      ['Status', STATUS_LABELS[payload.status]],
      ...RUN_STATUSES.map((status) => [STATUS_LABELS[status], payload.counts[status]] as [string, number]),
      ['Total', payload.counts.total],
      ['Started', payload.durations.started_at ?? ''],
      ['Duration (ms)', payload.durations.execution_time_ms ?? ''],
      ['Snapshot taken', snapshot.created_at],
    ] as Array<[string, string | number]>,
    headers: ['Test', 'Status', 'Duration (ms)'],
    rows: payload.rows.map((row) => [row.name, STATUS_LABELS[row.status], row.execution_time_ms]),
  });

  return (
    <Shell>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5, alignItems: 'flex-start', mb: 2 }}>
        <Box sx={{ flex: '1 1 260px', minWidth: 0 }}>
          <StatusChip status={payload.status} />
          <Typography variant="h5" component="h1" data-testid="share-title" sx={{ mt: 1, wordBreak: 'break-word' }}>
            {payload.title}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Snapshot taken {formatDateTime(snapshot.created_at)} — later changes are not shown. Expires{' '}
            {formatDateTime(snapshot.expires_at)}.
          </Typography>
        </Box>
        <ExportMenu buildExport={buildExport} />
      </Box>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, mb: 2 }}>
          <StatTile label="Total" value={<span data-testid="count-total">{payload.counts.total}</span>} />
          {RUN_STATUSES.map((status) => (
            <StatTile
              key={status}
              label={STATUS_LABELS[status]}
              color={STATUS_COLORS[status]}
              value={<span data-testid={`count-${status}`}>{payload.counts[status]}</span>}
            />
          ))}
        </Box>
        <Box sx={{ maxWidth: 420 }}>
          <RunStatusDonut counts={payload.counts} exportId="share-donut" />
        </Box>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
          Started {formatDateTime(payload.durations.started_at)} · Finished {formatDateTime(payload.durations.completed_at)} ·
          Duration {formatDurationMs(payload.durations.execution_time_ms)}
        </Typography>
        {payload.safe_labels.length > 0 && (
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 1 }}>
            {payload.safe_labels.map((label) => (
              <Chip key={label} size="small" label={label} />
            ))}
          </Box>
        )}
      </Paper>

      {payload.rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          This snapshot lists no individual tests.
        </Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined" sx={{ maxWidth: '100%', overflowX: 'auto' }}>
          <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 480, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
<colgroup><col /><col style={{ width: 120 }} /><col style={{ width: 110 }} /></colgroup>
            <TableHead>
              <TableRow>
                <TableCell>Test</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Duration</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {payload.rows.map((row, index) => (
                <TableRow key={`${row.name}-${index}`} data-testid="share-row">
                  <TableCell sx={{ wordBreak: 'break-word' }}>{row.name}</TableCell>
                  <TableCell>
                    <StatusChip status={row.status} />
                  </TableCell>
                  <TableCell align="right">{formatDurationMs(row.execution_time_ms)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
      {payload.rows_truncated && (
        <Typography variant="caption" color="text.secondary" data-testid="share-rows-truncated">
          Only the first {payload.rows.length} tests are included in this snapshot; the counts cover the whole run.
        </Typography>
      )}
    </Shell>
  );
};

export default ShareRun;

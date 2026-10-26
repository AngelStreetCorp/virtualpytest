/**
 * Run group detail: latest attempt per logical test (script + UI + environment +
 * host/device), attempts counted separately, and all / failures-only rerun.
 *
 * Rerun idempotency: one key per confirmed click, reused by "Retry" after a failure so
 * a request that reached the server is never dispatched twice; dropped after success.
 */

import { PushPin as PinIcon, PushPinOutlined as UnpinIcon } from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
  Link,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import React, { useCallback, useRef, useState } from 'react';
import { Link as RouterLink, useParams } from 'react-router-dom';

import ChartCard from '../components/analytics/ChartCard';
import StatTile from '../components/analytics/StatTile';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { ExportMenu, type ExportPayload } from '../components/reports/ExportMenu';
import { EmptyState, QueryState, ReportPage } from '../components/reports/PageState';
import { RunStatusDonut } from '../components/reports/RunCharts';
import { RunHeader } from '../components/reports/RunHeader';
import {
  STATUS_COLORS,
  STATUS_LABELS,
  StatusChip,
  formatDateTime,
} from '../components/reports/status';
import * as rmApi from '../hooks/reports/runManagementApi';
import { describeError } from '../hooks/reports/runManagementApi';
import {
  useGovernanceMutations,
  useGroupReport,
  useReportPermissions,
  useReportScope,
} from '../hooks/reports/useRunManagement';
import { useToast } from '../hooks/useToast';
import {
  REPORT_ROUTES,
  RUN_STATUSES,
  type RerunMode,
  type RerunResponse,
  type RunStatus,
  type RunStatusCounts,
} from '../types/reports';
import { ARCHIVE_HINT } from './RunGroups';
import { neutralButtonSx } from '../components/common/PageChrome';
import { useAgentChatPalette } from '../constants/agentChatTheme';

/** Group verdict from its latest-attempt rollup; never more confident than the counts. */
export const deriveGroupStatus = (counts: RunStatusCounts): RunStatus => {
  if (counts.failed > 0) return 'failed';
  if (counts.running > 0) return 'running';
  if (counts.pending > 0) return 'pending';
  if (counts.total > 0 && counts.passed === counts.total) return 'passed';
  return 'unknown';
};

/** Rerun with a stable idempotency key across retries of the same action. */
export const useGroupRerun = (groupId: string) => {
  const scope = useReportScope();
  const pending = useRef<{ mode: RerunMode; key: string } | null>(null);
  const [running, setRunning] = useState(false);
  const [failedMode, setFailedMode] = useState<RerunMode | null>(null);
  const [result, setResult] = useState<RerunResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const rerun = useCallback(
    async (mode: RerunMode) => {
      if (!pending.current || pending.current.mode !== mode) {
        pending.current = { mode, key: rmApi.newIdempotencyKey() };
      }
      setRunning(true);
      setError(null);
      try {
        const response = await rmApi.rerunGroup(groupId, { mode, idempotency_key: pending.current.key }, scope);
        pending.current = null;
        setFailedMode(null);
        setResult(response);
        return response;
      } catch (err) {
        setFailedMode(mode);
        setError(describeError(err));
        return null;
      } finally {
        setRunning(false);
      }
    },
    [groupId, scope],
  );

  return { rerun, running, failedMode, result, error };
};

const MODE_TEXT: Record<RerunMode, string> = {
  all: 'Rerun the latest attempt of every test in this group?',
  failures: 'Rerun every test whose latest attempt failed?',
};

const RunGroupDetail: React.FC = () => {
  const P = useAgentChatPalette();
  const { groupId = '' } = useParams<{ groupId: string }>();
  const report = useGroupReport(groupId);
  const { canEdit, canRerun } = useReportPermissions();
  const { updateGroup, archiveGroup, restoreGroup } = useGovernanceMutations();
  const { showError, showSuccess } = useToast();
  const [confirmMode, setConfirmMode] = useState<RerunMode | null>(null);
  const groupRerun = useGroupRerun(groupId);

  const run = async (action: () => Promise<unknown>, success: string) => {
    try {
      await action();
      showSuccess(success);
    } catch (err) {
      showError(describeError(err));
    }
  };

  const confirmRerun = async () => {
    const mode = confirmMode;
    setConfirmMode(null);
    if (!mode) return;
    const response = await groupRerun.rerun(mode);
    if (response) void report.refetch();
  };

  const data = report.data;

  const buildExport = (): ExportPayload => ({
    title: data?.group.name ?? 'Run group',
    summary: [
      ['Latest-attempt total', data?.counts.total ?? 0],
      ...RUN_STATUSES.map((s) => [STATUS_LABELS[s], data?.counts[s] ?? 0] as [string, number]),
      ['All attempts', data?.attempts_total ?? 0],
    ],
    headers: ['Test', 'Status', 'UI', 'Environment', 'Host', 'Device', 'Attempts', 'Started'],
    rows: (data?.rows ?? []).map((r) => [
      r.name,
      STATUS_LABELS[r.status],
      r.userinterface_name,
      r.environment,
      r.host_name,
      r.device_name,
      r.attempts,
      r.started_at,
    ]),
  });

  const rerunAllowed = canEdit && canRerun;

  return (
    <ReportPage>
      <QueryState loading={report.isLoading} error={report.error}>
        {data && (
          <>
            <RunHeader
              kind="group"
              title={data.group.name}
              status={deriveGroupStatus(data.counts)}
              subtitle={
                <Typography variant="body2" color="text.secondary">
                  {data.group.archived ? `Archived. ${ARCHIVE_HINT}` : data.group.description}
                </Typography>
              }
              actions={
                <>
                  <Button size="small" component={RouterLink} to={REPORT_ROUTES.summary('group', data.group.id)}>
                    View summary
                  </Button>
                  {rerunAllowed && (
                    <>
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => setConfirmMode('all')}
                        disabled={groupRerun.running || data.rows.length === 0}
                      >
                        Rerun all
                      </Button>
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => setConfirmMode('failures')}
                        disabled={groupRerun.running || data.counts.failed === 0}
                        sx={neutralButtonSx(P)}
                      >
                        Rerun failures
                      </Button>
                    </>
                  )}
                  {canEdit && (
                    <Button
                      size="small"
                      startIcon={data.group.pinned ? <PinIcon fontSize="small" /> : <UnpinIcon fontSize="small" />}
                      onClick={() =>
                        void run(
                          () => updateGroup.mutateAsync({ id: data.group.id, input: { pinned: !data.group.pinned } }),
                          data.group.pinned ? 'Unpinned' : 'Pinned',
                        )
                      }
                    >
                      {data.group.pinned ? 'Unpin' : 'Pin'}
                    </Button>
                  )}
                  {canEdit &&
                    (data.group.archived ? (
                      <Button size="small" onClick={() => void run(() => restoreGroup.mutateAsync(data.group.id), 'Restored')}>
                        Restore
                      </Button>
                    ) : (
                      <Button size="small" onClick={() => void run(() => archiveGroup.mutateAsync(data.group.id), 'Archived')}>
                        Archive
                      </Button>
                    ))}
                  <ExportMenu buildExport={buildExport} chartExportId="group-donut" />
                </>
              }
            />

            {groupRerun.error && (
              <Alert
                severity="error"
                sx={{ mb: 2 }}
                action={
                  groupRerun.failedMode && (
                    <Button
                      color="inherit"
                      size="small"
                      onClick={() => void groupRerun.rerun(groupRerun.failedMode as RerunMode)}
                      disabled={groupRerun.running}
                    >
                      Retry
                    </Button>
                  )
                }
              >
                Rerun failed: {groupRerun.error}
              </Alert>
            )}
            {groupRerun.result && (
              <Alert
                severity={groupRerun.result.status === 'failed' ? 'warning' : 'success'}
                sx={{ mb: 2 }}
                data-testid="rerun-result"
              >
                Dispatched {groupRerun.result.dispatched.length} run
                {groupRerun.result.dispatched.length === 1 ? '' : 's'}; skipped {groupRerun.result.skipped_manual.length}{' '}
                manual and {groupRerun.result.skipped_not_in_mode.length} not eligible (not in the mode, discarded, or
                not replayable from the server).
                {groupRerun.result.dispatched.length > 0 &&
                  ' Each run is queued on its original target; the new results appear in Test Reports when the host has run them.'}
                {groupRerun.result.idempotent_replay && ' This request was already received; nothing new was dispatched.'}
                {groupRerun.result.error && ` Dispatch stopped: ${groupRerun.result.error}`}
              </Alert>
            )}

            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3, mb: 2 }}>
              <StatTile label="Tests" value={<span data-testid="count-total">{data.counts.total}</span>} dense />
              {RUN_STATUSES.map((status) => (
                <StatTile
                  key={status}
                  label={STATUS_LABELS[status]}
                  value={<span data-testid={`count-${status}`}>{data.counts[status]}</span>}
                  color={data.counts[status] ? STATUS_COLORS[status] : undefined}
                  dense
                />
              ))}
              <StatTile label="All attempts" value={data.attempts_total} dense />
            </Box>

            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, mb: 2 }}>
              <ChartCard title="Latest attempt per test" minHeight={140} flex="1 1 280px">
                <RunStatusDonut counts={data.counts} exportId="group-donut" />
              </ChartCard>
            </Box>

            {data.rows.length === 0 ? (
              <EmptyState message="No results are assigned to this group yet. Assign results from Test Reports." />
            ) : (
              <Box sx={{ overflowX: 'auto' }}>
                <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 900, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
<colgroup><col /><col style={{ width: 110 }} /><col style={{ width: 150 }} /><col style={{ width: 110 }} /><col style={{ width: 150 }} /><col style={{ width: 90 }} /><col style={{ width: 190 }} /></colgroup>
                  <TableHead>
                    <TableRow>
                      <TableCell>Test</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell>UI</TableCell>
                      <TableCell>Environment</TableCell>
                      <TableCell>Target</TableCell>
                      <TableCell>Attempts</TableCell>
                      <TableCell>Started</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {data.rows.map((row, index) => (
                      <TableRow key={row.script_result_id ?? `row-${index}`} data-testid="child-row">
                        <TableCell sx={{ maxWidth: 300, wordBreak: 'break-word' }}>
                          {row.script_result_id ? (
                            <Link component={RouterLink} to={REPORT_ROUTES.summary('script', row.script_result_id)}>
                              {row.name}
                            </Link>
                          ) : (
                            row.name
                          )}
                        </TableCell>
                        <TableCell>
                          <StatusChip status={row.status} />
                        </TableCell>
                        <TableCell>{row.userinterface_name ?? '—'}</TableCell>
                        <TableCell>{row.environment ?? '—'}</TableCell>
                        <TableCell>{[row.host_name, row.device_name].filter(Boolean).join(' · ') || '—'}</TableCell>
                        <TableCell>{row.attempts}</TableCell>
                        <TableCell>{formatDateTime(row.started_at)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Box>
            )}

            <ConfirmDialog
              open={confirmMode !== null}
              title={confirmMode === 'failures' ? 'Rerun failures' : 'Rerun all'}
              message={`${confirmMode ? MODE_TEXT[confirmMode] : ''}\n\nManual runs are never replayed. Previous attempts stay unchanged; each rerun adds a new attempt.`}
              confirmText="Rerun"
              onConfirm={() => void confirmRerun()}
              onCancel={() => setConfirmMode(null)}
            />
          </>
        )}
      </QueryState>
    </ReportPage>
  );
};

export default RunGroupDetail;

/**
 * Live view of one running task: status, elapsed time, optional progress/ETA, an
 * authorized Stop, and a hand-off to the run summary once a durable result exists.
 * Nothing here is inferred: progress, totals and ETA only show when the producer reports them.
 */

import { Alert, Box, Button, Card, CardContent, LinearProgress, Link, Typography } from '@mui/material';
import React, { useEffect, useRef, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { ConfirmDialog } from '../common/ConfirmDialog';
import { describeError, stopLiveRun } from '../../hooks/reports/runManagementApi';
import { useLiveRun, type SystemEventSubscribe } from '../../hooks/reports/useLiveRun';
import { useReportPermissions, useReportScope } from '../../hooks/reports/useRunManagement';
import { REPORT_ROUTES, isTerminalStatus } from '../../types/reports';
import { StatusChip, formatDateTime, formatDurationMs } from './status';

export interface RunLivePanelProps {
  taskId: string;
  onCompleted?: (scriptResultId: string | null) => void;
  subscribe?: SystemEventSubscribe;
}

export const RunLivePanel: React.FC<RunLivePanelProps> = ({ taskId, onCompleted, subscribe }) => {
  const { data, error, stale, lastSuccessAt, refetch } = useLiveRun(taskId, { subscribe });
  const { canStop } = useReportPermissions();
  const scope = useReportScope();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [stopMessage, setStopMessage] = useState<{ severity: 'success' | 'error'; text: string } | null>(null);
  const [clock, setClock] = useState(() => Date.now());
  const completedRef = useRef(false);

  const status = data?.status ?? 'unknown';
  const active = status === 'running' || status === 'pending';
  const terminal = isTerminalStatus(status);

  // Tick the elapsed time between polls while the run is active.
  useEffect(() => {
    if (!active) return undefined;
    const id = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);

  useEffect(() => {
    if (terminal && data && !completedRef.current) {
      completedRef.current = true;
      onCompleted?.(data.script_result_id);
    }
  }, [terminal, data, onCompleted]);

  const elapsedMs =
    data?.elapsed_ms === null || data?.elapsed_ms === undefined
      ? null
      : data.elapsed_ms + (active && lastSuccessAt !== null ? Math.max(0, clock - lastSuccessAt) : 0);

  const total = data?.progress?.total;
  const completed = data?.progress?.completed;
  const hasProgress = typeof total === 'number' && total > 0 && typeof completed === 'number';

  const handleStop = async () => {
    setConfirmOpen(false);
    setStopping(true);
    setStopMessage(null);
    try {
      const response = await stopLiveRun(taskId, scope);
      setStopMessage(
        response.success
          ? { severity: 'success', text: 'Stop requested. The status updates when the host confirms.' }
          : { severity: 'error', text: 'The host did not confirm the stop.' },
      );
      refetch();
    } catch (err) {
      setStopMessage({ severity: 'error', text: describeError(err) });
    } finally {
      setStopping(false);
    }
  };

  if (!data && error) {
    return (
      <Alert severity="error" data-testid="live-error">
        Live status unavailable: {describeError(error)}
      </Alert>
    );
  }

  return (
    <Card variant="outlined" data-testid="run-live-panel">
      <CardContent>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1 }}>
          <StatusChip status={status} />
          <Typography variant="subtitle1" sx={{ wordBreak: 'break-word' }}>
            {data?.script_name ?? 'Run'}
          </Typography>
          {(data?.host_name || data?.device_name) && (
            <Typography variant="body2" color="text.secondary">
              {data?.host_name ?? 'unknown host'} / {data?.device_name ?? 'unknown device'}
            </Typography>
          )}
        </Box>

        {stale && (
          <Alert severity="warning" sx={{ mb: 1 }} data-testid="live-stale">
            Status may be out of date — last update{' '}
            {lastSuccessAt ? formatDateTime(new Date(lastSuccessAt).toISOString()) : 'never'}.
          </Alert>
        )}
        {!data && !error && (
          <Typography variant="body2" color="text.secondary">
            Waiting for the first status…
          </Typography>
        )}

        {data && (
          <Box sx={{ display: 'grid', gap: 0.5 }}>
            <Typography variant="body2">
              Elapsed: {elapsedMs === null ? 'not reported' : formatDurationMs(elapsedMs)}
            </Typography>
            {hasProgress ? (
              <Box>
                <LinearProgress
                  variant="determinate"
                  value={Math.min(100, ((completed as number) / (total as number)) * 100)}
                  aria-label="progress"
                />
                <Typography variant="caption" color="text.secondary">
                  {completed} of {total}
                </Typography>
              </Box>
            ) : (
              <Typography variant="body2" color="text.secondary">
                Progress not reported by this run
              </Typography>
            )}
            {data.eta_ms !== null && data.eta_ms !== undefined && (
              <Typography variant="body2">Estimated remaining: {formatDurationMs(data.eta_ms)}</Typography>
            )}
          </Box>
        )}

        {stopMessage && (
          <Alert severity={stopMessage.severity} sx={{ mt: 1 }}>
            {stopMessage.text}
          </Alert>
        )}

        {data && active && canStop && data.can_stop && (
          <Box sx={{ mt: 2 }}>
            <Button color="error" variant="outlined" onClick={() => setConfirmOpen(true)} disabled={stopping}>
              Stop run
            </Button>
          </Box>
        )}

        {data && terminal && (
          <Box sx={{ mt: 2 }} data-testid="live-finished">
            <Typography variant="body2" sx={{ mb: 0.5 }}>
              Run finished.
            </Typography>
            {data.script_result_id ? (
              <Link component={RouterLink} to={REPORT_ROUTES.summary('script', data.script_result_id)}>
                Open run summary
              </Link>
            ) : (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Typography variant="body2" color="text.secondary">
                  Waiting for the durable result…
                </Typography>
                <Button size="small" onClick={refetch}>
                  Refresh
                </Button>
              </Box>
            )}
          </Box>
        )}
      </CardContent>
      <ConfirmDialog
        open={confirmOpen}
        title="Stop this run?"
        message={'Stops the script process on the host. Releasing the device is not the same as stopping.'}
        confirmText="Stop run"
        confirmColor="error"
        onConfirm={() => void handleStop()}
        onCancel={() => setConfirmOpen(false)}
      />
    </Card>
  );
};

export default RunLivePanel;

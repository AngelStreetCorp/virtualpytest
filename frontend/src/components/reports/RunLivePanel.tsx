/**
 * Live view of one running task (TASK-127 G4): meta line, "Now: step N" with percent and chips,
 * the live device stream with the step frame strip, the Steps panel, the log built from the step
 * events, an authorized Stop, and a hand-off to the run summary once a durable result exists.
 * Nothing here is inferred: progress, totals and ETA only show when the producer reports them.
 */

import { Alert, Box, Button, Card, CardContent, Link, Typography } from '@mui/material';
import React, { useEffect, useRef, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { ConfirmDialog } from '../common/ConfirmDialog';
import { describeError, stopLiveRun } from '../../hooks/reports/runManagementApi';
import { useLiveRun, type SystemEventSubscribe } from '../../hooks/reports/useLiveRun';
import { useReportPermissions, useReportScope } from '../../hooks/reports/useRunManagement';
import { REPORT_ROUTES, isTerminalStatus } from '../../types/reports';
import { StatusChip, formatDateTime, formatDurationMs } from './status';
import { dangerButtonSx } from '../common/PageChrome';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { AppIcon } from '../../constants/icons';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import { useTargetSelection } from '../../hooks/useTargetSelection';
import { useLiveRunSteps } from '../../hooks/reports/useLiveRunSteps';
import { LiveStreamCard, RunLog, RunNowPanel, StepsPanel } from '../run-live';

export interface RunLivePanelProps {
  taskId: string;
  onCompleted?: (scriptResultId: string | null) => void;
  subscribe?: SystemEventSubscribe;
}

export const RunLivePanel: React.FC<RunLivePanelProps> = ({ taskId, onCompleted, subscribe }) => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const { allHosts, getDevicesFromHost } = useTargetSelection();
  const [frame, setFrame] = useState<number | null>(null);
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

  const deviceId = (data as (typeof data & { device_id?: string | null }) | null)?.device_id ?? '';
  const live = useLiveRunSteps(taskId, data?.host_name, deviceId, active);
  const totalSteps = live.totalSteps ?? data?.progress?.total ?? null;
  const device = data?.host_name ? { hostName: data.host_name, deviceId } : null;
  const startedLabel = data?.started_at ? formatDateTime(data.started_at) : null;

  const handleStop = async () => {
    setConfirmOpen(false);
    setStopping(true);
    setStopMessage(null);
    try {
      const response = await stopLiveRun(taskId, scope);
      setStopMessage(
        response.success
          ? { severity: 'success', text: t('Stop requested. The status updates when the host confirms.') }
          : { severity: 'error', text: t('The host did not confirm the stop.') },
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
        {t('Live status unavailable: {error}', { error: describeError(error) })}
      </Alert>
    );
  }

  return (
    <Box data-testid="run-live-panel" sx={{ display: 'grid', gap: 1.5, minWidth: 0 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <Typography sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.cardTitle.size, wordBreak: 'break-word' }}>{data?.script_name ?? t('Run')}</Typography>
        <StatusChip status={status} />
        <Box sx={{ flex: 1 }} />
        {data && active && canStop && data.can_stop && (
          <Button variant="outlined" startIcon={<AppIcon name="stop" />} onClick={() => setConfirmOpen(true)} disabled={stopping} sx={dangerButtonSx(P)}>
            {t('Stop run')}
          </Button>
        )}
      </Box>
      {data && (
        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', color: P.textSecondary, fontSize: TYPOGRAPHY.caption.size }}>
          {(data.host_name || data.device_name) && (
            <span>{data.device_name ?? t('unknown device')} · {data.host_name ?? t('unknown host')}</span>
          )}
          {startedLabel && <span>{t('Started {time}', { time: startedLabel })}</span>}
          <span>
            <b>{elapsedMs === null ? t('not reported') : formatDurationMs(elapsedMs)}</b> {t('elapsed')}
          </span>
        </Box>
      )}

      {stale && (
        <Alert severity="warning" data-testid="live-stale">
          {t('Status may be out of date — last update {time}.', {
            time: lastSuccessAt ? formatDateTime(new Date(lastSuccessAt).toISOString()) : t('never'),
          })}
        </Alert>
      )}
      {!data && !error && (
        <Typography variant="body2" color="text.secondary">
          {t('Waiting for the first status…')}
        </Typography>
      )}

      {data && (
        <>
          <Card variant="outlined">
            <CardContent>
              <RunNowPanel
                steps={live.steps}
                totalSteps={totalSteps}
                running={active}
                message={live.message}
                etaMs={data.eta_ms}
              />
            </CardContent>
          </Card>

          <Box sx={{ display: 'grid', gap: 1.5, gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 3fr) minmax(0, 2fr)' } }}>
            <Card variant="outlined">
              <CardContent>
                <LiveStreamCard
                  device={device}
                  streamProps={{ allHosts, getDevicesFromHost, isActive: active }}
                  steps={live.steps}
                  running={active}
                  selected={frame}
                  onSelect={setFrame}
                  caption={device ? `${data.device_name ?? deviceId} · ${data.host_name}` : undefined}
                />
              </CardContent>
            </Card>
            <Card variant="outlined">
              <CardContent>
                <Typography sx={{ fontWeight: 600, mb: 0.75 }}>
                  {t('Steps')} <Typography component="span" variant="caption" sx={{ color: P.textSecondary }}>{tn(live.steps.length, '{count} step', '{count} steps')}</Typography>
                </Typography>
                <StepsPanel
                  steps={live.steps}
                  running={active}
                  maxHeight={380}
                  resetKey={taskId}
                  selectedNumber={frame}
                  onSelect={(step) => setFrame(step.screenshot ? step.number : null)}
                />
              </CardContent>
            </Card>
          </Box>

          <RunLog steps={live.steps} fileName={`${data.script_name ?? 'run'}-${taskId.slice(0, 8)}`} />
        </>
      )}

      {stopMessage && <Alert severity={stopMessage.severity}>{stopMessage.text}</Alert>}

      {data && terminal && (
        <Box data-testid="live-finished">
          <Typography variant="body2" sx={{ mb: 0.5 }}>
            {t('Run finished.')}
          </Typography>
          {data.script_result_id ? (
            <Link component={RouterLink} to={REPORT_ROUTES.summary('script', data.script_result_id)}>
              {t('Open run summary')}
            </Link>
          ) : (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="body2" color="text.secondary">
                {t('Waiting for the durable result…')}
              </Typography>
              <Button size="small" onClick={refetch}>
                {t('Refresh')}
              </Button>
            </Box>
          )}
        </Box>
      )}
      <ConfirmDialog
        open={confirmOpen}
        title={t('Stop this run?')}
        message={t('Stops the script process on the host. Releasing the device is not the same as stopping.')}
        confirmText={t('Stop run')}
        confirmColor="error"
        onConfirm={() => void handleStop()}
        onCancel={() => setConfirmOpen(false)}
      />
    </Box>
  );
};

export default RunLivePanel;

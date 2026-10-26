import React, { useEffect, useState } from 'react';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Tooltip,
  Typography,
} from '@mui/material';
import { StopCircle as StopIcon } from '@mui/icons-material';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import type { LiveRunProgress } from '../../hooks/script/useLiveScriptProgress';
import type { ExecutionHistoryRow } from './ExecutionHistoryTable';
import { dangerButtonSx } from './PageChrome';
import type { DeviceStreamGridProps } from './DeviceStreaming/DeviceStreamGrid';
import { TYPOGRAPHY } from '../../constants/typography';
import { LiveStreamCard, RunNowPanel, StepsPanel, StepLine, formatElapsed } from '../run-live';

const useElapsed = (startedAtMs?: number): string | null => {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return startedAtMs ? formatElapsed(now - startedAtMs) : null;
};

const TooltipBody: React.FC<{ row: ExecutionHistoryRow; progress?: LiveRunProgress; startedAtMs?: number }> = ({ row, progress, startedAtMs }) => {
  const P = useAgentChatPalette();
  const { tn } = useI18n();
  const elapsed = useElapsed(startedAtMs);
  const steps = progress?.steps ?? [];
  return (
    <Box sx={{ width: 300, maxWidth: '80vw', p: 0.5 }}>
      <Typography variant="caption" sx={{ fontWeight: 600, display: 'block' }}>{row.scriptLabel}</Typography>
      <Typography variant="caption" sx={{ color: P.textSecondary, display: 'block', mb: steps.length ? 0.5 : 0 }}>
        {[row.targetLabel, elapsed, steps.length ? tn(steps.length, '{count} step', '{count} steps') : null].filter(Boolean).join(' · ')}
      </Typography>
      {steps.slice(-3).map((step) => <StepLine key={step.number} step={step} maxChars={32} />)}
    </Box>
  );
};

interface LiveRunStatusCellProps {
  row: ExecutionHistoryRow;
  progress?: LiveRunProgress;
  onOpen: (row: ExecutionHistoryRow) => void;
  children: React.ReactNode;
}

/** Wraps the unchanged status cell of a running row: hover = tooltip, click = Live run dialog. */
export const LiveRunStatusCell: React.FC<LiveRunStatusCellProps> = ({ row, progress, onOpen, children }) => (
  <Tooltip
    arrow
    placement="top"
    title={<TooltipBody row={row} progress={progress} startedAtMs={row.startedAtMs} />}
  >
    <Box
      component="span"
      role="button"
      tabIndex={0}
      onClick={(event) => { event.stopPropagation(); onOpen(row); }}
      onKeyDown={(event) => { if (event.key === 'Enter') { event.stopPropagation(); onOpen(row); } }}
      sx={{ cursor: 'pointer', display: 'inline-flex' }}
    >
      {children}
    </Box>
  </Tooltip>
);

interface LiveRunDialogProps {
  row: ExecutionHistoryRow | null;
  progress?: LiveRunProgress;
  onClose: () => void;
  onStop: (row: ExecutionHistoryRow) => void;
  streamProps: Omit<DeviceStreamGridProps, 'devices'>;
}

export const LiveRunDialog: React.FC<LiveRunDialogProps> = ({ row, progress, onClose, onStop, streamProps }) => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const elapsed = useElapsed(row?.startedAtMs);
  const [frame, setFrame] = useState<number | null>(null);
  const steps = progress?.steps ?? [];
  if (!row) return null;
  const running = row.status === 'running';
  const total = progress?.totalSteps ?? null;
  const stream = row.abortPayload
    ? { hostName: row.abortPayload.hostName, deviceId: row.abortPayload.deviceId || '' }
    : null;

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth PaperProps={{ sx: { borderRadius: 3, border: `1px solid ${P.borderColor}` } }}>
      <DialogTitle sx={{ pb: 0.5 }}>
        <Box sx={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 1 }}>
          <Typography component="div" noWrap sx={{ fontSize: TYPOGRAPHY.navbarItem.size, fontWeight: 600, minWidth: 0 }}>{row.scriptLabel}</Typography>
          {running && elapsed ? <Typography component="div" variant="caption" sx={{ color: P.textSecondary, whiteSpace: 'nowrap' }}>{elapsed}</Typography> : null}
        </Box>
        <Typography component="div" variant="caption" sx={{ color: P.textSecondary }}>
          {[row.targetLabel, tn(steps.length, '{count} step done', '{count} steps done')].join(' · ')}
        </Typography>
      </DialogTitle>
      <DialogContent>
        {total ? (
          <Box sx={{ mt: 1 }}>
            <RunNowPanel compact steps={steps} totalSteps={total} running={running} message={progress?.message} />
          </Box>
        ) : null}
        {stream || steps.some((s) => s.screenshot) ? (
          <Box sx={{ mt: 1.5 }}>
            <LiveStreamCard
              device={stream}
              streamProps={streamProps}
              steps={steps}
              running={running}
              selected={frame}
              onSelect={setFrame}
            />
          </Box>
        ) : null}
        <Box sx={{ mt: 1.5 }}>
          <StepsPanel steps={steps} running={false} maxHeight={180} resetKey={row.id} />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} sx={{ color: P.textSecondary }}>{t('Close')}</Button>
        {running && row.abortPayload ? (
          <Button startIcon={<StopIcon />} sx={dangerButtonSx(P)} onClick={() => onStop(row)}>{t('Stop')}</Button>
        ) : null}
      </DialogActions>
    </Dialog>
  );
};

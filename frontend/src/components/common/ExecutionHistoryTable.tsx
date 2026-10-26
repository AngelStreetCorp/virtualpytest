import React, { useMemo, useState } from 'react';
import { Box, IconButton, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Tooltip, Typography } from '@mui/material';
import { DescriptionOutlined as ReportIcon, Terminal as LogsIcon, ExpandMore as ExpandMoreIcon, ExpandLess as ExpandLessIcon, PlayArrow as ScriptIcon, CheckCircle as PassIcon, Error as FailIcon, RestartAlt as RerunIcon, HourglassTop as RunningIcon, Schedule as QueuedIcon, Block as AbortedIcon, RemoveCircleOutline as SkippedIcon, StopCircle as AbortIcon } from '@mui/icons-material';
import { SxProps, Theme } from '@mui/material/styles';

import type { RerunPayload } from '../../types/common/Rerun_Types';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { dangerIconSx, rateColor } from './PageChrome';
import type { Palette } from './PageChrome';
import { LiveRunStatusCell } from './LiveRunDialog';
import type { LiveRunProgress } from '../../hooks/script/useLiveScriptProgress';
import { TYPOGRAPHY } from '../../constants/typography';

export type ExecutionHistoryColumnKey = 'target' | 'script' | 'start' | 'end' | 'status' | 'report' | 'logs' | 'rerun' | 'result' | 'duration';

export interface ExecutionHistoryScriptRow {
  id: string;
  scriptName: string;
  success: boolean;
  durationLabel?: string;
  reportUrl?: string;
  logsUrl?: string;
}

export interface ExecutionHistoryRow {
  id: string;
  targetLabel: string;
  scriptLabel: string;
  startedLabel: string;
  completedLabel: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'aborted' | 'skipped';
  resultSuccess?: boolean | null;
  // CLI parameters this script/device ran with, shown as a hover tooltip on the
  // script name. Absent for campaigns / rows that carry no parameters.
  parametersLabel?: string;
  reportUrl?: string;
  logsUrl?: string;
  campaignScripts?: ExecutionHistoryScriptRow[];
  hideTopLevelLogs?: boolean;
  // Full launch-time config for one-click rerun. When absent the rerun cell
  // renders empty (e.g. older deployment rows that predate the column).
  rerunPayload?: RerunPayload;
  // Live-run view of a running script (Run Tests): target key the progress events are keyed by, and start time.
  liveKey?: string;
  startedAtMs?: number;
  completedAtMs?: number;
  // Passed / total steps when the source carries them; campaigns fall back to their scripts.
  stepsPassed?: number;
  stepsTotal?: number;
  abortPayload?: { hostName: string; deviceId?: string; executionType: 'script' | 'testcase' | 'campaign' };
}

interface ExecutionHistoryTableProps {
  rows: ExecutionHistoryRow[];
  onOpenUrl: (url: string) => void;
  onRerun?: (payload: RerunPayload) => void;
  onAbort?: (row: ExecutionHistoryRow) => void;
  /** Hover = step tooltip, click = Live run dialog on the status cell of running rows. */
  liveRun?: { getProgress: (row: ExecutionHistoryRow) => LiveRunProgress | undefined; onOpen: (row: ExecutionHistoryRow) => void };
  scriptColumnLabel?: string;
  /** Adds Result (bar + pass rate) and Duration columns and a relative Started time. */
  richColumns?: boolean;
  headerCellSx?: (key: ExecutionHistoryColumnKey) => SxProps<Theme> | undefined;
  bodyCellSx?: (key: ExecutionHistoryColumnKey) => SxProps<Theme> | undefined;
  renderHeaderExtra?: (key: ExecutionHistoryColumnKey) => React.ReactNode;
  tableSx?: SxProps<Theme>;
}

// Rows sit on the card colour and take the palette hover tint (the global table theme
// paints its own row colours, hence the !important).
const getRowHoverSx = (hoverBg: string): SxProps<Theme> => ({
  backgroundColor: 'transparent',
  '& > .MuiTableCell-root': {
    backgroundColor: 'transparent !important',
  },
  '&:hover > .MuiTableCell-root': {
    backgroundColor: `${hoverBg} !important`,
  },
});

const columns: Array<{ key: ExecutionHistoryColumnKey; label: string }> = [
  { key: 'target', label: 'Target' },
  { key: 'script', label: 'Script' },
  { key: 'start', label: 'Started' },
  { key: 'end', label: 'Completed' },
  { key: 'result', label: 'Result' },
  { key: 'duration', label: 'Duration' },
  { key: 'status', label: 'Status' },
  { key: 'report', label: 'Report' },
  { key: 'logs', label: 'Logs' },
  { key: 'rerun', label: 'Action' },
];

const formatRelative = (ms: number, now: number): string => {
  const sec = Math.max(0, Math.round((now - ms) / 1000));
  if (sec < 60) return 'just now';
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
};

const formatDuration = (ms: number): string => {
  const sec = Math.round(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m}m ${String(sec % 60).padStart(2, '0')}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`;
};

const getRowCounts = (row: ExecutionHistoryRow): { passed: number; total: number } | null => {
  if (row.stepsTotal) return { passed: row.stepsPassed ?? 0, total: row.stepsTotal };
  const scripts = row.campaignScripts ?? [];
  return scripts.length ? { passed: scripts.filter((s) => s.success).length, total: scripts.length } : null;
};

/** Passed/failed bar plus the pass rate in rateColor; nothing when the row has no counts. */
const ResultCell: React.FC<{ row: ExecutionHistoryRow; P: Palette }> = ({ row, P }) => {
  const counts = getRowCounts(row);
  if (!counts) return <Typography variant="caption" color="text.disabled">-</Typography>;
  const pct = Math.round((counts.passed / counts.total) * 100);
  return (
    <Tooltip title={`${counts.passed} passed, ${counts.total - counts.passed} failed`}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
        <Box sx={{ flex: 1, minWidth: 30, height: 6, borderRadius: 3, overflow: 'hidden', display: 'flex', bgcolor: P.hoverBg }}>
          <Box sx={{ width: `${pct}%`, bgcolor: P.success }} />
          <Box sx={{ width: `${100 - pct}%`, bgcolor: P.error }} />
        </Box>
        <Typography variant="caption" sx={{ fontWeight: 600, color: rateColor(pct, P), fontVariantNumeric: 'tabular-nums' }}>{pct}%</Typography>
      </Box>
    </Tooltip>
  );
};

export const getExecutionHistoryStatusChip = (row: ExecutionHistoryRow): React.JSX.Element => <ExecutionStatus row={row} />;

/** Status as a coloured icon + word (Passed / Failed / Running …), colours from the app palette. */
const ExecutionStatus: React.FC<{ row: ExecutionHistoryRow }> = ({ row }) => {
  const P = useAgentChatPalette();
  const status = row.status === 'completed' && row.resultSuccess != null
    ? (row.resultSuccess ? 'success' : 'failure')
    : row.status;
  const statusView: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
    success: { label: 'Passed', color: P.success, icon: <PassIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} /> },
    failure: { label: 'Failed', color: P.error, icon: <FailIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} /> },
    completed: { label: 'Completed', color: P.success, icon: <PassIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} /> },
    failed: { label: 'Failed', color: P.error, icon: <FailIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} /> },
    running: { label: 'Running', color: P.accentText, icon: <RunningIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} /> },
    queued: { label: 'Queued', color: P.textSecondary, icon: <QueuedIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} /> },
    aborted: { label: 'Aborted', color: P.warning, icon: <AbortedIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} /> },
    skipped: { label: 'Skipped', color: P.textMuted, icon: <SkippedIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} /> },
  };
  const view = statusView[status] ?? { label: status, color: P.textMuted, icon: <SkippedIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} /> };
  return (
    <Box component="span" aria-label={view.label} sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, color: view.color, fontSize: TYPOGRAPHY.caption.size, fontWeight: 600, verticalAlign: 'middle', whiteSpace: 'nowrap' }}>
      {view.icon}
      {view.label}
    </Box>
  );
};

export const ExecutionHistoryTable: React.FC<ExecutionHistoryTableProps> = ({
  rows,
  onOpenUrl,
  onRerun,
  onAbort,
  liveRun,
  scriptColumnLabel,
  richColumns = false,
  headerCellSx,
  bodyCellSx,
  renderHeaderExtra,
  tableSx,
}) => {
  const now = Date.now();
  // Result needs pass/fail counts; with none in view the column would be empty, so it is hidden.
  const showResult = richColumns && rows.some((r) => getRowCounts(r) !== null);
  const visibleColumns = columns.filter((c) => (c.key === 'result' ? showResult : c.key === 'duration' ? richColumns : true));
  const [expandedExecutionId, setExpandedExecutionId] = useState<string | null>(null);
  const P = useAgentChatPalette();
  const rowHoverSx = useMemo(() => getRowHoverSx(P.hoverBg), [P.hoverBg]);
  const linkSx = { color: P.textSecondary, '&:hover': { color: P.accentText, bgcolor: P.hoverBg } };

  // ui-ok: table-layout — every caller passes tableLayout: 'fixed' (+ its column widths) through tableSx
  return (
    <TableContainer component={Paper} variant="outlined" sx={{ overflowX: 'hidden', borderRadius: 2, borderColor: P.borderColor }}>
      <Table
        size="small"
        sx={{
          '& .MuiTableCell-root': { borderColor: P.borderColor },
          '& thead .MuiTableCell-root': { fontSize: TYPOGRAPHY.caption.size, fontWeight: 600, color: `${P.textSecondary} !important`, bgcolor: `${P.hoverBg} !important` },
          ...(tableSx as object),
        }}
      >
        <TableHead>
          <TableRow>
            {visibleColumns.map(({ key, label }) => {
              const displayLabel = key === 'script' && scriptColumnLabel ? scriptColumnLabel : label;
              const centered = key === 'status' || key === 'report' || key === 'logs' || key === 'rerun';
              return (
                <TableCell key={key} sx={{ ...headerCellSx?.(key) as object, ...(centered ? { textAlign: 'center' } : {}) }}>
                  {displayLabel}
                  {renderHeaderExtra?.(key)}
                </TableCell>
              );
            })}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => {
            const hasScripts = (row.campaignScripts?.length ?? 0) > 0;
            const isExpanded = expandedExecutionId === row.id;

            return (
              <React.Fragment key={row.id}>
                <TableRow
                  sx={{ ...rowHoverSx as Record<string, unknown>, ...(hasScripts ? { cursor: 'pointer' } : {}) }}
                  onClick={() => hasScripts && setExpandedExecutionId(isExpanded ? null : row.id)}
                >
                  <TableCell sx={bodyCellSx?.('target')}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      {hasScripts && (
                        <IconButton size="small" sx={{ p: 0 }}>
                          {isExpanded ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
                        </IconButton>
                      )}
                      <Typography variant="body2">{row.targetLabel}</Typography>
                    </Box>
                  </TableCell>
                  <TableCell sx={bodyCellSx?.('script')}>
                    <Tooltip
                      arrow
                      title={
                        <Box sx={{ whiteSpace: 'pre-line', fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size, maxWidth: 420 }}>
                          <strong>{row.scriptLabel}</strong>
                          {row.parametersLabel ? `\n${row.parametersLabel}` : ''}
                        </Box>
                      }
                    >
                      <Typography
                        variant="body2"
                        component="span"
                        sx={{ cursor: 'help', borderBottom: '1px dotted', borderColor: 'text.disabled' }}
                      >
                        {row.scriptLabel}
                      </Typography>
                    </Tooltip>
                  </TableCell>
                  <TableCell sx={bodyCellSx?.('start')}>
                    <Tooltip title={richColumns && row.startedAtMs ? row.startedLabel : ''}>
                      <Typography variant="caption" color={row.startedLabel !== '-' ? 'text.primary' : 'text.disabled'} sx={{ whiteSpace: 'nowrap' }}>
                        {richColumns && row.startedAtMs ? formatRelative(row.startedAtMs, now) : row.startedLabel}
                      </Typography>
                    </Tooltip>
                  </TableCell>
                  <TableCell sx={bodyCellSx?.('end')}>
                      <Typography variant="caption" color={row.completedLabel !== '-' ? 'text.primary' : 'text.disabled'} sx={{ whiteSpace: 'nowrap' }}>
                      {row.completedLabel}
                    </Typography>
                  </TableCell>
                  {richColumns && (
                    <>
                      {showResult && <TableCell sx={bodyCellSx?.('result')}><ResultCell row={row} P={P} /></TableCell>}
                      <TableCell sx={bodyCellSx?.('duration')}>
                        <Typography variant="caption" color={row.startedAtMs && row.completedAtMs ? 'text.primary' : 'text.disabled'} sx={{ whiteSpace: 'nowrap' }}>
                          {row.startedAtMs && row.completedAtMs ? formatDuration(row.completedAtMs - row.startedAtMs) : '-'}
                        </Typography>
                      </TableCell>
                    </>
                  )}
                  <TableCell sx={{ ...bodyCellSx?.('status') as object, textAlign: 'center' }}>
                    {liveRun && row.status === 'running' && row.liveKey ? (
                      <LiveRunStatusCell row={row} progress={liveRun.getProgress(row)} onOpen={liveRun.onOpen}>
                        {getExecutionHistoryStatusChip(row)}
                      </LiveRunStatusCell>
                    ) : getExecutionHistoryStatusChip(row)}
                  </TableCell>
                  <TableCell sx={{ ...bodyCellSx?.('report') as object, textAlign: 'center' }}>
                    {row.reportUrl ? (
                      <Tooltip title="Open report">
                        <IconButton aria-label="Open report" size="small" sx={linkSx} onClick={(event) => { event.stopPropagation(); onOpenUrl(row.reportUrl!); }}>
                          <ReportIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    ) : (
                      <Tooltip title="No report available"><span><IconButton aria-label="No report available" size="small" disabled><ReportIcon fontSize="small" /></IconButton></span></Tooltip>
                    )}
                  </TableCell>
                  <TableCell sx={{ ...bodyCellSx?.('logs') as object, textAlign: 'center' }}>
                    {row.hideTopLevelLogs ? (
                      ''
                    ) : row.logsUrl ? (
                      <Tooltip title="Open logs">
                        <IconButton aria-label="Open logs" size="small" sx={linkSx} onClick={(event) => { event.stopPropagation(); onOpenUrl(row.logsUrl!); }}>
                          <LogsIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    ) : (
                      <Tooltip title="No logs available"><span><IconButton aria-label="No logs available" size="small" disabled><LogsIcon fontSize="small" /></IconButton></span></Tooltip>
                    )}
                  </TableCell>
                  <TableCell sx={{ ...bodyCellSx?.('rerun') as object, textAlign: 'center' }}>
                    {row.status === 'running' && row.abortPayload && onAbort ? (
                      <Tooltip title="Abort execution">
                        <IconButton
                          size="small"
                          aria-label="Abort execution"
                          onClick={(event) => { event.stopPropagation(); onAbort(row); }}
                          sx={dangerIconSx(P)}
                        >
                          <AbortIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    ) : row.rerunPayload && onRerun ? (
                      <Tooltip title="Rerun on the same device with the same script and parameters">
                        <IconButton
                          size="small"
                          onClick={(event) => {
                            event.stopPropagation();
                            onRerun(row.rerunPayload!);
                          }}
                          sx={linkSx}
                        >
                          <RerunIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    ) : null}
                  </TableCell>
                </TableRow>
                {hasScripts && isExpanded && (row.campaignScripts || []).map((script) => (
                  <TableRow key={script.id} sx={rowHoverSx as Record<string, unknown>}>
                    <TableCell sx={bodyCellSx?.('target')}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, pl: 4 }}>
                        <ScriptIcon fontSize="small" sx={{ flexShrink: 0, opacity: 0.6 }} />
                        <Typography variant="body2" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {script.scriptName}
                        </Typography>
                      </Box>
                    </TableCell>
                    <TableCell sx={bodyCellSx?.('script')} />
                    <TableCell sx={bodyCellSx?.('start')} />
                    <TableCell sx={bodyCellSx?.('end')}>
                      <Typography variant="caption" sx={{ opacity: 0.8 }}>
                        {script.durationLabel || '-'}
                      </Typography>
                    </TableCell>
                    {richColumns && (
                      <>
                        {showResult && <TableCell sx={bodyCellSx?.('result')} />}
                        <TableCell sx={bodyCellSx?.('duration')}>
                          <Typography variant="caption" sx={{ opacity: 0.8 }}>{script.durationLabel || '-'}</Typography>
                        </TableCell>
                      </>
                    )}
                    <TableCell sx={{ ...bodyCellSx?.('status') as object, textAlign: 'center' }}>
                      <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, fontSize: TYPOGRAPHY.caption.size, fontWeight: 600, color: script.success ? P.success : P.error }}>
                        {script.success ? <PassIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} /> : <FailIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />}
                        {script.success ? 'Passed' : 'Failed'}
                      </Box>
                    </TableCell>
                    <TableCell sx={{ ...bodyCellSx?.('report') as object, textAlign: 'center' }}>
                      {script.reportUrl ? (
                        <IconButton aria-label="Open report" size="small" sx={linkSx} onClick={(event) => { event.stopPropagation(); onOpenUrl(script.reportUrl!); }}>
                          <ReportIcon fontSize="small" />
                        </IconButton>
                      ) : null}
                    </TableCell>
                    <TableCell sx={{ ...bodyCellSx?.('logs') as object, textAlign: 'center' }}>
                      {script.logsUrl ? (
                        <IconButton aria-label="Open logs" size="small" sx={linkSx} onClick={(event) => { event.stopPropagation(); onOpenUrl(script.logsUrl!); }}>
                          <LogsIcon fontSize="small" />
                        </IconButton>
                      ) : null}
                    </TableCell>
                    {/* Rerun cell intentionally empty for campaign sub-rows. */}
                    <TableCell sx={{ ...bodyCellSx?.('rerun') as object }} />
                  </TableRow>
                ))}
              </React.Fragment>
            );
          })}
        </TableBody>
      </Table>
    </TableContainer>
  );
};

export default ExecutionHistoryTable;

import React, { useMemo, useState } from 'react';
import { Box, Chip, IconButton, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Tooltip, Typography } from '@mui/material';
import { Link as LinkIcon, ExpandMore as ExpandMoreIcon, ExpandLess as ExpandLessIcon, PlayArrow as ScriptIcon, CheckCircle as PassIcon, Error as FailIcon, RestartAlt as RerunIcon, HourglassTop as RunningIcon, Schedule as QueuedIcon, Block as AbortedIcon, RemoveCircleOutline as SkippedIcon, StopCircle as AbortIcon } from '@mui/icons-material';
import { SxProps, Theme } from '@mui/material/styles';

import type { RerunPayload } from '../../types/common/Rerun_Types';

export type ExecutionHistoryColumnKey = 'target' | 'script' | 'start' | 'end' | 'status' | 'report' | 'logs' | 'rerun';

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
  abortPayload?: { hostName: string; deviceId?: string; executionType: 'script' | 'testcase' | 'campaign' };
}

interface ExecutionHistoryTableProps {
  rows: ExecutionHistoryRow[];
  onOpenUrl: (url: string) => void;
  onRerun?: (payload: RerunPayload) => void;
  onAbort?: (row: ExecutionHistoryRow) => void;
  scriptColumnLabel?: string;
  headerCellSx?: (key: ExecutionHistoryColumnKey) => SxProps<Theme> | undefined;
  bodyCellSx?: (key: ExecutionHistoryColumnKey) => SxProps<Theme> | undefined;
  renderHeaderExtra?: (key: ExecutionHistoryColumnKey) => React.ReactNode;
  tableSx?: SxProps<Theme>;
}

const getTransparentHoverSx = (): SxProps<Theme> => ({
  backgroundColor: 'transparent',
  '& > .MuiTableCell-root': {
    backgroundColor: 'transparent !important',
  },
  '&:hover': {
    backgroundColor: 'transparent !important',
  },
  '&:hover > .MuiTableCell-root': {
    backgroundColor: 'transparent !important',
  },
});

const columns: Array<{ key: ExecutionHistoryColumnKey; label: string }> = [
  { key: 'target', label: 'Target' },
  { key: 'script', label: 'Script' },
  { key: 'start', label: 'Started' },
  { key: 'end', label: 'Completed' },
  { key: 'status', label: 'Status' },
  { key: 'report', label: 'Report' },
  { key: 'logs', label: 'Logs' },
  { key: 'rerun', label: 'Action' },
];

export const getExecutionHistoryStatusChip = (row: ExecutionHistoryRow): React.JSX.Element => {
  const status = row.status === 'completed' && row.resultSuccess != null
    ? (row.resultSuccess ? 'success' : 'failure')
    : row.status;
  const statusView: Record<string, { label: string; color: 'success' | 'error' | 'warning' | 'info' | 'disabled'; icon: React.ReactNode }> = {
    success: { label: 'Passed', color: 'success', icon: <PassIcon fontSize="small" /> },
    failure: { label: 'Failed', color: 'error', icon: <FailIcon fontSize="small" /> },
    completed: { label: 'Completed', color: 'success', icon: <PassIcon fontSize="small" /> },
    failed: { label: 'Failed', color: 'error', icon: <FailIcon fontSize="small" /> },
    running: { label: 'Running', color: 'warning', icon: <RunningIcon fontSize="small" /> },
    queued: { label: 'Queued', color: 'info', icon: <QueuedIcon fontSize="small" /> },
    aborted: { label: 'Aborted', color: 'error', icon: <AbortedIcon fontSize="small" /> },
    skipped: { label: 'Skipped', color: 'disabled', icon: <SkippedIcon fontSize="small" /> },
  };
  const view = statusView[status] ?? { label: status, color: 'disabled' as const, icon: <SkippedIcon fontSize="small" /> };
  return (
    <Tooltip title={view.label} arrow>
      <Box component="span" aria-label={view.label} sx={{ display: 'inline-flex', color: view.color === 'disabled' ? 'text.disabled' : `${view.color}.main`, verticalAlign: 'middle' }}>
        {view.icon}
      </Box>
    </Tooltip>
  );
};

export const ExecutionHistoryTable: React.FC<ExecutionHistoryTableProps> = ({
  rows,
  onOpenUrl,
  onRerun,
  onAbort,
  scriptColumnLabel,
  headerCellSx,
  bodyCellSx,
  renderHeaderExtra,
  tableSx,
}) => {
  const [expandedExecutionId, setExpandedExecutionId] = useState<string | null>(null);
  const rowHoverSx = useMemo(() => getTransparentHoverSx(), []);

  return (
    <TableContainer component={Paper} variant="outlined" sx={{ overflowX: 'hidden' }}>
      <Table size="small" sx={tableSx}>
        <TableHead>
          <TableRow>
            {columns.map(({ key, label }) => {
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
                        <Box sx={{ whiteSpace: 'pre-line', fontFamily: 'monospace', fontSize: '0.7rem', maxWidth: 420 }}>
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
                      <Typography variant="caption" color={row.startedLabel !== '-' ? 'text.primary' : 'text.disabled'} sx={{ whiteSpace: 'nowrap' }}>
                      {row.startedLabel}
                    </Typography>
                  </TableCell>
                  <TableCell sx={bodyCellSx?.('end')}>
                      <Typography variant="caption" color={row.completedLabel !== '-' ? 'text.primary' : 'text.disabled'} sx={{ whiteSpace: 'nowrap' }}>
                      {row.completedLabel}
                    </Typography>
                  </TableCell>
                  <TableCell sx={{ ...bodyCellSx?.('status') as object, textAlign: 'center' }}>
                    {getExecutionHistoryStatusChip(row)}
                  </TableCell>
                  <TableCell sx={{ ...bodyCellSx?.('report') as object, textAlign: 'center' }}>
                    {row.reportUrl ? (
                      <Tooltip title="Open report">
                        <IconButton aria-label="Open report" size="small" color="primary" onClick={(event) => { event.stopPropagation(); onOpenUrl(row.reportUrl!); }}>
                          <LinkIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    ) : (
                      <Tooltip title="No report available"><span><IconButton aria-label="No report available" size="small" disabled><LinkIcon fontSize="small" /></IconButton></span></Tooltip>
                    )}
                  </TableCell>
                  <TableCell sx={{ ...bodyCellSx?.('logs') as object, textAlign: 'center' }}>
                    {row.hideTopLevelLogs ? (
                      ''
                    ) : row.logsUrl ? (
                      <Tooltip title="Open logs">
                        <IconButton aria-label="Open logs" size="small" color="secondary" onClick={(event) => { event.stopPropagation(); onOpenUrl(row.logsUrl!); }}>
                          <LinkIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    ) : (
                      <Tooltip title="No logs available"><span><IconButton aria-label="No logs available" size="small" disabled><LinkIcon fontSize="small" /></IconButton></span></Tooltip>
                    )}
                  </TableCell>
                  <TableCell sx={{ ...bodyCellSx?.('rerun') as object, textAlign: 'center' }}>
                    {row.status === 'running' && row.abortPayload && onAbort ? (
                      <Tooltip title="Abort execution">
                        <IconButton
                          size="small"
                          color="error"
                          aria-label="Abort execution"
                          onClick={(event) => { event.stopPropagation(); onAbort(row); }}
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
                          color="primary"
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
                    <TableCell sx={{ ...bodyCellSx?.('status') as object, textAlign: 'center' }}>
                      <Chip
                        icon={script.success ? <PassIcon /> : <FailIcon />}
                        label={script.success ? 'PASS' : 'FAIL'}
                        color={script.success ? 'success' : 'error'}
                        size="small"
                        sx={{ height: '18px', fontSize: '0.65rem' }}
                      />
                    </TableCell>
                    <TableCell sx={{ ...bodyCellSx?.('report') as object, textAlign: 'center' }}>
                      {script.reportUrl ? (
                        <Chip
                          label="Report"
                          clickable
                          onClick={(event) => { event.stopPropagation(); onOpenUrl(script.reportUrl!); }}
                          size="small"
                          icon={<LinkIcon />}
                          color="primary"
                          variant="outlined"
                        />
                      ) : null}
                    </TableCell>
                    <TableCell sx={{ ...bodyCellSx?.('logs') as object, textAlign: 'center' }}>
                      {script.logsUrl ? (
                        <Chip
                          label="Logs"
                          clickable
                          onClick={(event) => { event.stopPropagation(); onOpenUrl(script.logsUrl!); }}
                          size="small"
                          icon={<LinkIcon />}
                          color="secondary"
                          variant="outlined"
                        />
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

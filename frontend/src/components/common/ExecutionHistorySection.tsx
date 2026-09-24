import React from 'react';
import {
  Box,
  Card,
  CardContent,
  Chip,
  Collapse,
  Grid,
  IconButton,
  Tooltip,
  Typography,
} from '@mui/material';
import { ExpandMore as ExpandMoreIcon, ExpandLess as ExpandLessIcon, Link as LinkIcon, RestartAlt as RerunIcon, StopCircle as AbortIcon } from '@mui/icons-material';
import { SxProps, Theme } from '@mui/material/styles';

import ExecutionHistoryTable, {
  ExecutionHistoryColumnKey,
  ExecutionHistoryRow,
  getExecutionHistoryStatusChip,
} from './ExecutionHistoryTable';
import type { RerunPayload } from '../../types/common/Rerun_Types';

interface ExecutionHistorySectionProps {
  title: string;
  rows: ExecutionHistoryRow[];
  emptyMessage: string;
  onOpenUrl: (url: string) => void;
  onRerun?: (payload: RerunPayload) => void;
  onAbort?: (row: ExecutionHistoryRow) => void;
  scriptColumnLabel?: string;
  isCompact?: boolean;
  isTablet?: boolean;
  collapsible?: boolean;
  expanded?: boolean;
  onToggleExpanded?: () => void;
  cardSx?: SxProps<Theme>;
  contentSx?: SxProps<Theme>;
  headerCellSx?: (key: ExecutionHistoryColumnKey) => SxProps<Theme> | undefined;
  bodyCellSx?: (key: ExecutionHistoryColumnKey) => SxProps<Theme> | undefined;
  renderHeaderExtra?: (key: ExecutionHistoryColumnKey) => React.ReactNode;
  /** Rendered on the title row, right-aligned — e.g. a result filter. */
  titleExtra?: React.ReactNode;
  tableSx?: SxProps<Theme>;
}

const ExecutionHistorySection: React.FC<ExecutionHistorySectionProps> = ({
  title,
  rows,
  emptyMessage,
  onOpenUrl,
  onRerun,
  onAbort,
  scriptColumnLabel,
  isCompact = false,
  isTablet = false,
  collapsible = false,
  expanded = true,
  onToggleExpanded,
  cardSx,
  contentSx,
  headerCellSx,
  bodyCellSx,
  renderHeaderExtra,
  titleExtra,
  tableSx,
}) => {
  const content = rows.length === 0 ? (
    <Box
      sx={{
        p: 2,
        textAlign: 'center',
        borderRadius: 1,
        backgroundColor: 'background.default',
      }}
    >
      <Typography variant="body2" color="text.secondary">
        {emptyMessage}
      </Typography>
    </Box>
  ) : isCompact ? (
    <Grid container spacing={1}>
      {rows.map((row) => (
        <Grid item xs={12} sm={isTablet ? 6 : 12} key={row.id}>
          <Card variant="outlined">
            <CardContent sx={{ py: 1.25 }}>
              <Typography variant="subtitle2">{row.targetLabel}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>
                {row.scriptLabel}
              </Typography>
              <Box sx={{ mt: 0.75, display: 'flex', gap: 0.5, flexWrap: 'wrap', alignItems: 'center' }}>
                {getExecutionHistoryStatusChip(row)}
                {row.reportUrl ? (
                  <Chip
                    label="Report"
                    clickable
                    onClick={() => onOpenUrl(row.reportUrl!)}
                    size="small"
                    icon={<LinkIcon />}
                    color="primary"
                    variant="outlined"
                  />
                ) : null}
                {!row.hideTopLevelLogs && row.logsUrl ? (
                  <Chip
                    label="Logs"
                    size="small"
                    clickable
                    onClick={() => onOpenUrl(row.logsUrl!)}
                    color="secondary"
                    variant="outlined"
                  />
                ) : null}
                {row.status === 'running' && row.abortPayload && onAbort ? (
                  <Tooltip title="Abort execution">
                    <IconButton size="small" color="error" aria-label="Abort execution" onClick={() => onAbort(row)}>
                      <AbortIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                ) : row.rerunPayload && onRerun ? (
                  <Tooltip title="Rerun on the same device with the same script and parameters">
                    <IconButton size="small" color="primary" onClick={() => onRerun(row.rerunPayload!)}>
                      <RerunIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                ) : null}
              </Box>
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.75 }}>
                {row.completedLabel !== '-' ? `${row.startedLabel} • ${row.completedLabel}` : row.startedLabel}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      ))}
    </Grid>
  ) : (
    <ExecutionHistoryTable
      rows={rows}
      onOpenUrl={onOpenUrl}
      onRerun={onRerun}
      onAbort={onAbort}
      scriptColumnLabel={scriptColumnLabel}
      headerCellSx={headerCellSx}
      bodyCellSx={bodyCellSx}
      renderHeaderExtra={renderHeaderExtra}
      tableSx={tableSx}
    />
  );

  return (
    <Card sx={cardSx}>
      <CardContent sx={contentSx}>
        {collapsible ? (
          <>
            <Box
              sx={{ display: 'flex', alignItems: 'center', cursor: 'pointer', mb: expanded ? 1 : 0 }}
              onClick={onToggleExpanded}
            >
              <IconButton size="small" sx={{ mr: 0.5, p: 0.25 }}>
                {expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
              </IconButton>
              <Typography variant="h6">{title}</Typography>
              {titleExtra ? (
                <Box sx={{ ml: 'auto' }} onClick={(e) => e.stopPropagation()}>{titleExtra}</Box>
              ) : null}
            </Box>
            <Collapse in={expanded}>
              {content}
            </Collapse>
          </>
        ) : (
          <>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1, flexWrap: 'wrap' }}>
              <Typography variant="h6">{title}</Typography>
              {titleExtra ? <Box sx={{ ml: 'auto' }}>{titleExtra}</Box> : null}
            </Box>
            {content}
          </>
        )}
      </CardContent>
    </Card>
  );
};

export default ExecutionHistorySection;

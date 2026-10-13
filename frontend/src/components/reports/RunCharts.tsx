/**
 * Run charts: thin wrappers over the analytics Donut / StackedBar so run reports share
 * one chart implementation with the Analytics tabs. Each wrapper only maps run data
 * (counts, trend points) onto those components and wraps them in a node the PNG
 * exporter can find (`data-export-chart`).
 */

import { Box } from '@mui/material';
import React from 'react';

import { Donut, StackedBar } from '../analytics/Charts';
import { RUN_STATUSES, type ReportChartPoint, type RunStatusCounts, type TrendPoint } from '../../types/reports';
import { STATUS_COLORS, STATUS_LABELS } from './status';

export interface RunStatusDonutProps {
  counts: RunStatusCounts;
  size?: number;
  exportId?: string;
}

/** Donut of status counts. Zero statuses stay in the legend so the absence is explicit. */
export const RunStatusDonut: React.FC<RunStatusDonutProps> = ({ counts, size = 132, exportId = 'status-donut' }) => {
  const data = RUN_STATUSES.map((status) => ({ name: STATUS_LABELS[status], value: counts[status] }));
  const colors = Object.fromEntries(RUN_STATUSES.map((status) => [STATUS_LABELS[status], STATUS_COLORS[status]]));
  return (
    <Box data-export-chart={exportId} sx={{ width: '100%' }}>
      <Donut data={data} colors={colors} centerValue={counts.total} centerLabel="total" size={size} />
    </Box>
  );
};

const OUTCOME_SERIES = [
  { key: 'passed', label: 'Passed', color: STATUS_COLORS.passed },
  { key: 'failed', label: 'Failed', color: STATUS_COLORS.failed },
  { key: 'other', label: 'Other terminal', color: STATUS_COLORS.skipped },
];

export interface RunTrendChartProps {
  points: TrendPoint[] | ReportChartPoint[];
  xKey?: 'day' | 'x';
  height?: number;
  shortenDates?: boolean;
  exportId?: string;
}

/** Stacked passed / failed / other per bucket (UTC days from the server, zero-filled). */
export const RunTrendChart: React.FC<RunTrendChartProps> = ({
  points,
  xKey = 'day',
  height = 180,
  shortenDates = true,
  exportId = 'trend',
}) => (
  <Box data-export-chart={exportId} sx={{ width: '100%' }}>
    <StackedBar
      data={points as unknown as Array<Record<string, unknown>>}
      xKey={xKey}
      series={OUTCOME_SERIES}
      height={height}
      shortenDates={shortenDates}
    />
  </Box>
);

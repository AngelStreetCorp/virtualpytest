import { Box, Typography, useTheme } from '@mui/material';
import React from 'react';
import {
  Bar,
  BarChart,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  Treemap,
  XAxis,
  YAxis,
} from 'recharts';

import { chrome, Mode } from './palette';
import { RankedItem } from './topN';

/**
 * Thin recharts wrappers, shared by every Analytics tab.
 *
 * Conventions applied here once so no individual chart has to remember them:
 *   - thin marks, hairline grid, recessive axes
 *   - a 2px surface gap between adjacent/stacked marks instead of a border
 *   - visible value labels rather than tooltip-only, which the light palette's
 *     sub-3:1 slots actually require (see palette.ts)
 *   - a legend whenever there are 2+ series; none for a single series, whose title
 *     already names it
 *   - one axis, always. Never a second y-scale.
 */

export const useMode = (): Mode => (useTheme().palette.mode === 'dark' ? 'dark' : 'light');

const axisStyle = (mode: Mode) => ({
  fontSize: 10,
  fill: chrome(mode).muted,
});

const tooltipStyle = (mode: Mode) => ({
  contentStyle: {
    background: chrome(mode).surface,
    border: `1px solid ${chrome(mode).grid}`,
    borderRadius: 6,
    fontSize: 11,
    padding: '6px 10px',
  },
  labelStyle: { color: chrome(mode).muted, fontSize: 10 },
  itemStyle: { padding: 0 },
});

// ---------------------------------------------------------------------------
// Horizontal bars — rankings, per-host resources
// ---------------------------------------------------------------------------

export interface HBarProps {
  data: RankedItem[];
  /** One colour for every bar (one series = one colour), or a per-row function. */
  color: string | ((row: RankedItem) => string);
  unit?: string;
  /** Fixed axis maximum, e.g. 100 for a percentage. */
  max?: number;
  labelWidth?: number;
  decimals?: number;
}

/**
 * Built from flex boxes rather than a recharts BarChart.
 *
 * A recharts horizontal bar chart needs a fixed pixel height per row to avoid
 * squashing labels, at which point it is doing less than a flex row does — and each
 * ResponsiveContainer carries its own ResizeObserver. With up to four ranking cards
 * per tab that is real cost for no gain. Value labels are always rendered, which is
 * what the light palette's low-contrast slots require anyway.
 */
export const HBar: React.FC<HBarProps> = ({
  data,
  color,
  unit = '',
  max,
  labelWidth = 120,
  decimals = 0,
}) => {
  const mode = useMode();
  const bound = max ?? Math.max(...data.map((d) => d.value), 1);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: '7px', width: '100%' }}>
      {data.map((row) => {
        const fill = typeof color === 'function' ? color(row) : color;
        const pct = Math.max(1.2, (row.value / bound) * 100);
        return (
          <Box key={row.name} sx={{ display: 'flex', alignItems: 'center', gap: 1.25 }}>
            <Typography
              variant="caption"
              title={row.name}
              sx={{
                width: labelWidth,
                flexShrink: 0,
                textAlign: 'right',
                color: 'text.secondary',
                fontSize: '0.6875rem',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {row.name}
            </Typography>
            <Box
              sx={{
                flexGrow: 1,
                height: 14,
                minWidth: 20,
                bgcolor: chrome(mode).track,
                borderRadius: '3px',
                overflow: 'hidden',
              }}
            >
              <Box
                sx={{
                  width: `${pct}%`,
                  height: '100%',
                  bgcolor: fill,
                  borderRadius: '3px',
                  opacity: row.is_others ? 0.45 : 1,
                }}
              />
            </Box>
            <Typography
              variant="caption"
              sx={{
                width: 54,
                flexShrink: 0,
                textAlign: 'right',
                color: 'text.secondary',
                fontSize: '0.6875rem',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {row.value.toFixed(decimals)}
              {unit}
            </Typography>
          </Box>
        );
      })}
    </Box>
  );
};

// ---------------------------------------------------------------------------
// Stacked vertical bars over time
// ---------------------------------------------------------------------------

export interface StackedBarProps {
  data: Array<Record<string, unknown>>;
  xKey: string;
  series: Array<{ key: string; label: string; color: string }>;
  height?: number;
  /** Shorten an ISO date to MM-DD for the axis. */
  shortenDates?: boolean;
}

export const StackedBar: React.FC<StackedBarProps> = ({
  data,
  xKey,
  series,
  height = 170,
  shortenDates = true,
}) => {
  const mode = useMode();
  const tick = axisStyle(mode);

  return (
    <ResponsiveContainer width="100%" height={height}>
      {/* No negative left margin: it pulls the plot over the y-axis band and clips the
          leading digits, so 220 renders as "20". Give the axis its own width instead. */}
      <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barCategoryGap="18%">
        <XAxis
          dataKey={xKey}
          tick={tick}
          tickLine={false}
          axisLine={{ stroke: chrome(mode).axis }}
          interval="preserveStartEnd"
          minTickGap={12}
          tickFormatter={(v: string) =>
            shortenDates && typeof v === 'string' && v.length === 10 ? v.slice(5) : v
          }
        />
        <YAxis
          tick={tick}
          tickLine={false}
          axisLine={false}
          width={44}
          allowDecimals={false}
        />
        <Tooltip cursor={{ fill: chrome(mode).track }} {...tooltipStyle(mode)} />
        {series.length > 1 && (
          <Legend
            iconType="square"
            iconSize={9}
            wrapperStyle={{ fontSize: 11, color: chrome(mode).muted, paddingTop: 6 }}
          />
        )}
        {series.map((s) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.label}
            stackId="a"
            fill={s.color}
            // 2px of surface between stacked segments instead of a stroke.
            stroke={chrome(mode).surface}
            strokeWidth={2}
            radius={[0, 0, 0, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
};

// ---------------------------------------------------------------------------
// Donut
// ---------------------------------------------------------------------------

export interface DonutProps {
  data: RankedItem[];
  colors: Record<string, string> | ((row: RankedItem) => string);
  centerValue?: React.ReactNode;
  centerLabel?: string;
  size?: number;
}

export const Donut: React.FC<DonutProps> = ({
  data,
  colors,
  centerValue,
  centerLabel,
  size = 132,
}) => {
  const mode = useMode();
  const shown = data.filter((d) => d.value > 0);
  const colorOf = (row: RankedItem) =>
    typeof colors === 'function' ? colors(row) : colors[row.name] || chrome(mode).muted;

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2.5, width: '100%' }}>
      <Box sx={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={shown}
              dataKey="value"
              nameKey="name"
              innerRadius={size * 0.32}
              outerRadius={size * 0.48}
              paddingAngle={2}
              startAngle={90}
              endAngle={-270}
              isAnimationActive={false}
              stroke={chrome(mode).surface}
              strokeWidth={2}
            >
              {shown.map((row) => (
                <Cell key={row.name} fill={colorOf(row)} />
              ))}
            </Pie>
            <Tooltip {...tooltipStyle(mode)} />
          </PieChart>
        </ResponsiveContainer>
        {centerValue != null && (
          <Box
            sx={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              pointerEvents: 'none',
            }}
          >
            <Typography variant="h6" sx={{ fontWeight: 600, lineHeight: 1 }}>
              {centerValue}
            </Typography>
            {centerLabel && (
              <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.625rem' }}>
                {centerLabel}
              </Typography>
            )}
          </Box>
        )}
      </Box>

      {/* The legend carries the numbers: identity is never colour alone, and the
          light palette's low-contrast slots need a visible value. */}
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, flexGrow: 1, minWidth: 0 }}>
        {data.map((row) => (
          <Box key={row.name} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Box
              sx={{
                width: 9,
                height: 9,
                borderRadius: '2px',
                bgcolor: colorOf(row),
                flexShrink: 0,
              }}
            />
            <Typography
              variant="caption"
              sx={{
                flexGrow: 1,
                color: 'text.secondary',
                fontSize: '0.6875rem',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {row.name}
            </Typography>
            <Typography
              variant="caption"
              sx={{ fontWeight: 600, fontSize: '0.6875rem', fontVariantNumeric: 'tabular-nums' }}
            >
              {row.value.toLocaleString()}
            </Typography>
          </Box>
        ))}
      </Box>
    </Box>
  );
};

// ---------------------------------------------------------------------------
// Treemap
// ---------------------------------------------------------------------------

interface TreemapContentProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  name?: string;
  value?: number;
  fill?: string;
  fillOpacity?: number;
  surface: string;
}

/** One cell. Colour identifies the area; the rectangle's size carries the magnitude. */
const TreemapCell: React.FC<TreemapContentProps> = ({
  x = 0,
  y = 0,
  width = 0,
  height = 0,
  name,
  value,
  fill,
  fillOpacity = 1,
  surface,
}) => {
  const roomForLabel = width > 64 && height > 30;
  const roomForValue = width > 96 && height > 46;
  return (
    <g>
      <rect
        x={x + 1}
        y={y + 1}
        width={Math.max(0, width - 2)}
        height={Math.max(0, height - 2)}
        rx={4}
        fill={fill}
        fillOpacity={fillOpacity}
        stroke={surface}
        strokeWidth={2}
      />
      {roomForLabel && (
        <text x={x + 10} y={y + 20} fill="#fff" fontSize={12} fontWeight={600}>
          {name}
        </text>
      )}
      {roomForValue && (
        <text x={x + 10} y={y + 36} fill="rgba(255,255,255,0.78)" fontSize={11}>
          {(value ?? 0).toLocaleString()}
        </text>
      )}
    </g>
  );
};

export interface CodeTreemapProps {
  data: RankedItem[];
  /** One colour per cell, in slot order. */
  colors: string[];
  height?: number;
}

/** recharts hands `content` the raw node props; this adapts them to TreemapCell. */
const TreemapCellAdapter: React.FC<any> = ({ surface, colors, ...node }) => (
  // Keyed by the cell's own index so an area keeps its colour as the data changes.
  <TreemapCell {...node} surface={surface} fill={colors[(node.index ?? 0) % colors.length]} />
);

export const CodeTreemap: React.FC<CodeTreemapProps> = ({ data, colors, height = 240 }) => {
  const mode = useMode();

  return (
    <ResponsiveContainer width="100%" height={height}>
      <Treemap
        data={data}
        dataKey="value"
        nameKey="name"
        isAnimationActive={false}
        content={<TreemapCellAdapter surface={chrome(mode).surface} colors={colors} />}
      >
        <Tooltip {...tooltipStyle(mode)} />
      </Treemap>
    </ResponsiveContainer>
  );
};

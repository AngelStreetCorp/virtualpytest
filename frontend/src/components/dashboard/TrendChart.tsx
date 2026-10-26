import { Box } from '@mui/material';
import React, { useId, useMemo, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';

import { pct } from './dashboardFormat';
import type { DashRange, TrendBucket } from './dashboardTypes';

const Y_TICKS = [100, 75, 50, 25, 0] as const;
const Y_AXIS_WIDTH = 40;
/** Space above and below the plot so the 100 % and 0 % labels are not clipped. */
const PLOT_MARGIN = '6px';

interface Point {
  /** Position in the bucket list, 0..n-1: a bucket without runs leaves a gap on the time axis, not a zero. */
  index: number;
  rate: number;
  passed: number;
  total: number;
  at: string;
}

/** HH:mm for a day, dd/mm beyond (the viewer's locale). */
export const formatAxisTime = (iso: string, range: DashRange): string => {
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return '';
  return range === '24h'
    ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString([], { day: '2-digit', month: '2-digit' });
};

/**
 * The hero chart: pass rate over time as a filled line, y axis 0 / 25 / 50 / 75 / 100 %, four time labels, the last
 * value printed at the end of the line and a tooltip under the pointer. Hand-drawn SVG: the plot stretches, the
 * labels and dots are HTML so they never distort.
 */
export const TrendChart: React.FC<{ trend: TrendBucket[]; range: DashRange }> = ({ trend, range }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const gradientId = useId();
  const [hover, setHover] = useState<number | null>(null);

  const points = useMemo<Point[]>(
    () =>
      trend
        .map((b, index) => ({ index, rate: pct(b.passed, b.total), passed: b.passed, total: b.total, at: b.bucket_start }))
        .filter((p) => p.total > 0),
    [trend],
  );
  const last = trend.length - 1;
  if (points.length < 2 || last < 1) return null;

  const x = (p: Point) => (p.index / last) * 100;
  const line = points.map((p) => `${x(p).toFixed(2)},${(100 - p.rate).toFixed(2)}`).join(' ');
  const first = points[0];
  const end = points[points.length - 1];
  const area = `${line} ${x(end).toFixed(2)},100 ${x(first).toFixed(2)},100`;
  const axisIdx = [0, Math.round(last / 3), Math.round((2 * last) / 3), last];
  const shown = hover !== null ? points[hover] : null;

  const onMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    if (box.width <= 0) return;
    const frac = ((e.clientX - box.left) / box.width) * 100;
    let best = 0;
    points.forEach((p, i) => {
      if (Math.abs(x(p) - frac) < Math.abs(x(points[best]) - frac)) best = i;
    });
    setHover(best);
  };

  const dot = (p: Point, strong: boolean) => (
    <Box
      sx={{
        position: 'absolute',
        left: `${x(p)}%`,
        top: `${100 - p.rate}%`,
        width: strong ? 9 : 7,
        height: strong ? 9 : 7,
        borderRadius: '50%',
        bgcolor: P.accentText,
        border: `2px solid ${P.surface}`,
        boxSizing: 'content-box',
        transform: 'translate(-50%, -50%)',
        pointerEvents: 'none',
      }}
    />
  );

  return (
    <Box data-testid="trend-chart" sx={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <Box sx={{ flex: 1, minHeight: 0, display: 'flex' }}>
        <Box sx={{ width: Y_AXIS_WIDTH, flexShrink: 0, position: 'relative', my: PLOT_MARGIN }} aria-hidden="true">
          {Y_TICKS.map((v) => (
            <Box
              key={v}
              sx={{ position: 'absolute', right: 8, top: `${100 - v}%`, transform: 'translateY(-50%)', whiteSpace: 'nowrap', fontSize: TYPOGRAPHY.microMeta.size, color: P.textMuted, lineHeight: 1 }}
            >
              {v} %
            </Box>
          ))}
        </Box>
        <Box
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
          sx={{ flex: 1, minWidth: 0, position: 'relative', my: PLOT_MARGIN }}
        >
          {Y_TICKS.map((v) => (
            <Box key={v} sx={{ position: 'absolute', left: 0, right: 0, top: `${100 - v}%`, height: '1px', bgcolor: P.borderColor }} />
          ))}
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" width="100%" height="100%" role="img" aria-label={t('Pass-rate trend')} style={{ position: 'absolute', inset: 0 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={P.accentText} stopOpacity="0.28" />
                <stop offset="100%" stopColor={P.accentText} stopOpacity="0" />
              </linearGradient>
            </defs>
            {points.length > 1 && <polygon points={area} fill={`url(#${gradientId})`} />}
            {points.length > 1 && <polyline fill="none" stroke={P.accentText} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" points={line} />}
          </svg>
          {dot(end, true)}
          {shown && shown !== end && dot(shown, false)}
          <Box
            data-testid="trend-last"
            sx={{
              position: 'absolute',
              left: `${x(end)}%`,
              top: `${100 - end.rate}%`,
              transform: end.rate > 70 ? 'translate(-100%, 10px)' : 'translate(-100%, calc(-100% - 8px))',
              pr: 0.5,
              whiteSpace: 'nowrap',
              fontSize: TYPOGRAPHY.caption.size,
              fontWeight: 600,
              color: P.accentText,
              pointerEvents: 'none',
            }}
          >
            {end.rate} %
          </Box>
          {shown && (
            <Box
              data-testid="trend-tooltip"
              sx={{
                position: 'absolute',
                left: `${Math.min(88, Math.max(12, x(shown)))}%`,
                top: shown.rate > 55 ? `${100 - shown.rate + 14}%` : `${100 - shown.rate - 4}%`,
                transform: shown.rate > 55 ? 'translate(-50%, 0)' : 'translate(-50%, -100%)',
                bgcolor: P.surface,
                border: `1px solid ${P.borderColor}`,
                borderRadius: 1.5,
                px: 1,
                py: 0.5,
                whiteSpace: 'nowrap',
                fontSize: TYPOGRAPHY.caption.size,
                color: P.textPrimary,
                pointerEvents: 'none',
                zIndex: 1,
              }}
            >
              {formatAxisTime(shown.at, range)} · {shown.rate} % · {shown.passed}/{shown.total}
            </Box>
          )}
        </Box>
      </Box>
      <Box sx={{ ml: `${Y_AXIS_WIDTH}px`, display: 'flex', justifyContent: 'space-between', fontSize: TYPOGRAPHY.microMeta.size, color: P.textMuted, lineHeight: 1.2 }}>
        {axisIdx.map((i, pos) => (
          <span key={pos}>{formatAxisTime(trend[i].bucket_start, range)}</span>
        ))}
      </Box>
    </Box>
  );
};

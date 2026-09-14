import { Box, Tooltip, Typography } from '@mui/material';
import React, { useMemo, useState } from 'react';

import {
  AVQMetric,
  PositionKind,
  SUBTITLE_PRESENT,
  TimelinePosition,
  TRANSCRIPT_PRESENT,
} from '../hooks/useAVQMetrics';
import {
  TimelineIncident,
  TimelineScript,
  TimelineZap,
} from '../hooks/useDeviceTimeline';

interface MetricRow {
  key: keyof AVQMetric;
  label: string;
  color: string;
  domain?: [number, number];
  unit?: string;
}

const METRIC_ROWS: MetricRow[] = [
  { key: 'video_mos', label: 'Video MOS', color: '#4caf50', domain: [1, 5] },
  { key: 'blurriness_score', label: 'Blur', color: '#9c27b0' },
  { key: 'blockiness_score', label: 'Blockiness', color: '#e91e63' },
  { key: 'blackscreen_seconds', label: 'Blackscreen', color: '#9e9e9e', domain: [0, 60], unit: 's' },
  { key: 'freeze_seconds', label: 'Freeze', color: '#f44336', domain: [0, 60], unit: 's' },
  { key: 'macroblocks_seconds', label: 'Macroblocks', color: '#ab47bc', domain: [0, 60], unit: 's' },
  { key: 'audio_mos', label: 'Audio MOS', color: '#2196f3', domain: [1, 5] },
  { key: 'loudness_lkfs', label: 'Loudness', color: '#00bcd4', unit: ' LKFS' },
  { key: 'silence_seconds', label: 'Silence', color: '#ff9800', domain: [0, 60], unit: 's' },
];

const INCIDENT_COLORS: Record<string, string> = {
  blackscreen: '#000000',
  freeze: '#f44336',
  audio_loss: '#ff9800',
  macroblocks: '#9c27b0',
};

// Position lane (Localize "where am I"): green = confident single node, yellow =
// ambiguous (low confidence / look-alike menus the title layer would break),
// plus named capture states. 'unknown' is NOT drawn — the grey lane shows through.
const POSITION_COLORS: Record<PositionKind, string> = {
  confident: '#4caf50',
  ambiguous: '#ffc107',
  no_signal: '#ff7043',
  blackscreen: '#000000',
  unknown: 'transparent',
};
const positionLabel = (p: TimelinePosition): string =>
  p.kind === 'no_signal'
    ? 'No Signal'
    : p.kind === 'blackscreen'
      ? 'Black Screen'
      : p.node || 'unknown';

const ROW_H = 30;
const LANE_H = 20;
const LABEL_W = 88;
const AXIS_H = 22;
// Alternating row stripe — applied coherently across metric rows AND lanes (and the
// label column) so every row is easy to track left-to-right.
const ROW_STRIPE = 'rgba(255,255,255,0.05)';
const LANE_LABELS = ['Position', 'Events', 'Scripts', 'Zaps', 'Transcript', 'Subtitles'];

interface AVQTimelineProps {
  metrics: AVQMetric[];
  incidents: TimelineIncident[];
  scripts: TimelineScript[];
  zaps: TimelineZap[];
  hours?: number;
  /** Called with the clicked wall-clock epoch ms (to seek the archive player). */
  onSeek?: (epochMs: number) => void;
  /** Persistent playhead at this epoch ms (the currently-sought time). */
  selectedTime?: number | null;
}

/**
 * One shared 24h time axis: a sparkline per metric (time-positioned), plus an
 * EVENTS (incidents) lane and a SCRIPTS (runs) lane. Dependency-free SVG.
 */
export const AVQTimeline: React.FC<AVQTimelineProps> = ({
  metrics,
  incidents,
  scripts,
  zaps,
  hours = 24,
  onSeek,
  selectedTime,
}) => {
  // Measure the available width so the timeline fills the panel (responsive).
  const wrapRef = React.useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  React.useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const update = () => setWidth(Math.max(320, el.clientWidth));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const t1 = Date.now();
  const t0 = t1 - hours * 3600_000;
  const x = (t: number) => ((t - t0) / (t1 - t0)) * width;

  const [hoverX, setHoverX] = useState<number | null>(null);
  // Hovered zap marker → interactive tooltip (info + link to the zap report).
  const [hoverZap, setHoverZap] = useState<TimelineZap | null>(null);
  const zapCloseTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const openZap = (z: TimelineZap) => {
    if (zapCloseTimer.current) clearTimeout(zapCloseTimer.current);
    setHoverZap(z);
  };
  const closeZapSoon = () => {
    if (zapCloseTimer.current) clearTimeout(zapCloseTimer.current);
    zapCloseTimer.current = setTimeout(() => setHoverZap(null), 150);
  };

  const points = useMemo(
    () => metrics.map((m) => ({ t: new Date(m.timestamp).getTime(), m })),
    [metrics],
  );

  const linePath = (row: MetricRow): string => {
    const vals = points
      .map((p) => ({ t: p.t, v: p.m[row.key] as number | null }))
      .filter((p) => p.t >= t0);
    const finite = vals.filter((p) => typeof p.v === 'number') as { t: number; v: number }[];
    if (finite.length === 0) return '';
    const lo = row.domain ? row.domain[0] : Math.min(...finite.map((p) => p.v));
    const hi = row.domain ? row.domain[1] : Math.max(...finite.map((p) => p.v));
    const span = hi - lo || 1;
    const segs: string[] = [];
    let started = false;
    vals.forEach((p) => {
      if (typeof p.v !== 'number') {
        started = false;
        return;
      }
      const px = x(p.t);
      // Clamp to [0,1] so out-of-domain values (e.g. silence 96s vs [0,60]) stay
      // inside the row band instead of spilling into the neighbouring row.
      const norm = Math.max(0, Math.min(1, (p.v - lo) / span));
      const py = ROW_H - norm * (ROW_H - 4) - 2;
      segs.push(`${started ? 'L' : 'M'}${px.toFixed(1)},${py.toFixed(1)}`);
      started = true;
    });
    return segs.join(' ');
  };

  const fmtRow = (row: MetricRow, v: number | null | undefined): string =>
    typeof v === 'number' ? `${Math.round(v * 100) / 100}${row.unit || ''}` : '—';

  const lastVal = (row: MetricRow): string => {
    for (let i = points.length - 1; i >= 0; i--) {
      const v = points[i].m[row.key] as number | null;
      if (typeof v === 'number') return fmtRow(row, v);
    }
    return '—';
  };

  const LANE_COUNT = LANE_LABELS.length; // POSITION, EVENTS, SCRIPTS, ZAPS, TRANSCRIPT, SUBTITLES
  const totalH = METRIC_ROWS.length * ROW_H + LANE_COUNT * (LANE_H + 6) + AXIS_H + 20;
  const laneTop = (i: number) => METRIC_ROWS.length * ROW_H + i * (LANE_H + 6) + 3;
  const zapsLaneTop = laneTop(3);

  // All Localize position spans across the loaded minutes, flattened + time-ordered.
  const positions = useMemo<TimelinePosition[]>(
    () =>
      metrics
        .flatMap((m) => m.positions ?? [])
        .filter((p) => p && p.kind !== 'unknown')
        .sort((a, b) => a.s - b.s),
    [metrics],
  );

  // Contiguous time spans where a per-sample value is present (> 0). Used to mark
  // the transcript / subtitle availability lanes so users can spot those sections.
  const presenceSpans = (key: keyof AVQMetric, threshold = 0): Array<[number, number]> => {
    const spans: Array<[number, number]> = [];
    let segStart: number | null = null;
    for (let i = 0; i < points.length; i++) {
      const v = points[i].m[key] as number | null;
      const present = typeof v === 'number' && v > threshold;
      if (present && segStart === null) segStart = points[i].t;
      if (!present && segStart !== null) {
        spans.push([segStart, points[i].t]);
        segStart = null;
      }
    }
    if (segStart !== null) spans.push([segStart, points[points.length - 1].t]);
    return spans;
  };

  // hour grid ticks
  const ticks: number[] = [];
  for (let h = 0; h <= hours; h += 3) ticks.push(t1 - (hours - h) * 3600_000);

  const nearestPoint = (t: number | null) => {
    if (t == null || points.length === 0) return null;
    let best = points[0];
    let bestD = Infinity;
    for (const p of points) {
      const d = Math.abs(p.t - t);
      if (d < bestD) {
        bestD = d;
        best = p;
      }
    }
    return best;
  };

  // Nearest sample to the hovered time — its values are shown inline on each row.
  const hoverTime = hoverX !== null ? t0 + (hoverX / width) * (t1 - t0) : null;
  const hoverPoint = useMemo(() => nearestPoint(hoverTime), [hoverTime, points]);
  // Nearest sample to the locked (yellow) playhead — values pinned on each row.
  const selectedPoint = useMemo(
    () => (selectedTime != null ? nearestPoint(selectedTime) : null),
    [selectedTime, points],
  );
  const selectedX = selectedTime != null ? x(selectedTime) : null;

  return (
    <Box sx={{ display: 'flex', width: '100%' }}>
      {/* labels column — same style + zebra parity as the chart rows */}
      <Box sx={{ width: LABEL_W, flexShrink: 0 }}>
        {METRIC_ROWS.map((r, i) => (
          <Box key={r.key as string} sx={{ height: ROW_H, display: 'flex', alignItems: 'center', px: 0.5, bgcolor: i % 2 ? ROW_STRIPE : 'transparent' }}>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              {r.label}
            </Typography>
          </Box>
        ))}
        {LANE_LABELS.map((l, j) => (
          <Box key={l} sx={{ height: LANE_H + 6, display: 'flex', alignItems: 'center', px: 0.5, bgcolor: (METRIC_ROWS.length + j) % 2 ? ROW_STRIPE : 'transparent' }}>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              {l}
            </Typography>
          </Box>
        ))}
      </Box>

      {/* svg timeline */}
      <Box ref={wrapRef} sx={{ position: 'relative', flex: 1, minWidth: 0 }}>
        <svg
          width={width}
          height={totalH}
          style={{ cursor: onSeek ? 'pointer' : 'default' }}
          onMouseMove={(e) => {
            const rect = (e.target as SVGElement).closest('svg')!.getBoundingClientRect();
            setHoverX(e.clientX - rect.left);
          }}
          onMouseLeave={() => setHoverX(null)}
          onClick={(e) => {
            if (!onSeek) return;
            const rect = (e.target as SVGElement).closest('svg')!.getBoundingClientRect();
            const px = e.clientX - rect.left;
            if (px < 0 || px > width) return;
            onSeek(t0 + (px / width) * (t1 - t0));
          }}
        >
          {/* hour gridlines */}
          {ticks.map((t, i) => (
            <line key={i} x1={x(t)} y1={0} x2={x(t)} y2={totalH - AXIS_H} stroke="#333" strokeWidth={1} />
          ))}

          {/* metric rows */}
          {METRIC_ROWS.map((r, i) => {
            const top = i * ROW_H;
            const path = linePath(r);
            // Inline value at the hovered time (anchored away from the right edge).
            const hoverV =
              hoverPoint && hoverX !== null ? (hoverPoint.m[r.key] as number | null) : null;
            const anchorRight = hoverX !== null && hoverX > width - 64;
            return (
              <g key={r.key as string} transform={`translate(0,${top})`}>
                <rect x={0} y={0} width={width} height={ROW_H} fill={i % 2 ? ROW_STRIPE : 'transparent'} />
                {/* row separator — same dashed stroke as the empty-metric rows */}
                <line x1={0} y1={ROW_H} x2={width} y2={ROW_H} stroke="#444" strokeWidth={1} strokeDasharray="3 3" />
                {path ? (
                  <path d={path} fill="none" stroke={r.color} strokeWidth={1.4} />
                ) : (
                  <line x1={0} y1={ROW_H / 2} x2={width} y2={ROW_H / 2} stroke="#555" strokeDasharray="3 3" />
                )}
                <text x={width - 4} y={12} textAnchor="end" fontSize={10} fill="#aaa">
                  {lastVal(r)}
                </text>
                {/* pinned value on the yellow (selected) playhead — always shown */}
                {selectedPoint && selectedX !== null && (
                  <text
                    x={selectedX > width - 64 ? selectedX - 6 : selectedX + 6}
                    y={12}
                    textAnchor={selectedX > width - 64 ? 'end' : 'start'}
                    fontSize={10}
                    fontWeight={700}
                    fill={r.color}
                    stroke="#000"
                    strokeWidth={3}
                    style={{ paintOrder: 'stroke' }}
                  >
                    {fmtRow(r, selectedPoint.m[r.key] as number | null)}
                  </text>
                )}
                {hoverPoint && hoverX !== null && (
                  <text
                    x={anchorRight ? hoverX - 6 : hoverX + 6}
                    y={12}
                    textAnchor={anchorRight ? 'end' : 'start'}
                    fontSize={10}
                    fontWeight={600}
                    fill={r.color}
                    stroke="#000"
                    strokeWidth={3}
                    style={{ paintOrder: 'stroke' }}
                  >
                    {fmtRow(r, hoverV)}
                  </text>
                )}
              </g>
            );
          })}

          {/* lane row stripes — continue the metric-row zebra parity */}
          {LANE_LABELS.map((l, j) => (
            <rect
              key={`lane-bg-${l}`}
              x={0}
              y={METRIC_ROWS.length * ROW_H + j * (LANE_H + 6)}
              width={width}
              height={LANE_H + 6}
              fill={(METRIC_ROWS.length + j) % 2 ? ROW_STRIPE : 'transparent'}
            />
          ))}

          {/* lane separators — same dashed stroke as the metric rows */}
          {Array.from({ length: LANE_COUNT }, (_, k) => k + 1).map((n) => (
            <line
              key={`lane-sep-${n}`}
              x1={0}
              y1={METRIC_ROWS.length * ROW_H + n * (LANE_H + 6)}
              x2={width}
              y2={METRIC_ROWS.length * ROW_H + n * (LANE_H + 6)}
              stroke="#444"
              strokeWidth={1}
              strokeDasharray="3 3"
            />
          ))}

          {/* POSITION lane — closest-known navigation node over time (Localize).
              Green = confident single node, yellow = ambiguous, plus named capture
              states; unknown stretches stay grey (lane background). */}
          <g transform={`translate(0,${laneTop(0)})`}>
            {positions.map((p, i) => {
              const xs = Math.max(0, x(p.s));
              const xe = Math.min(width, x(p.e));
              const w = xe - xs;
              if (w <= 0) return null;
              const label = positionLabel(p);
              return (
                <g key={`pos-${i}`}>
                  <rect
                    x={xs}
                    y={2}
                    width={Math.max(2, w)}
                    height={LANE_H - 4}
                    fill={POSITION_COLORS[p.kind]}
                    opacity={p.kind === 'ambiguous' ? 0.7 : 0.85}
                    rx={1}
                  >
                    <title>{`${label} · ${Math.round(p.conf * 100)}% · ${new Date(
                      p.s,
                    ).toLocaleTimeString()}`}</title>
                  </rect>
                  {/* node label inside the segment when it's wide enough to read */}
                  {w > 34 && (
                    <text
                      x={xs + 3}
                      y={LANE_H / 2 + 2}
                      fontSize={9}
                      fill={p.kind === 'blackscreen' ? '#ccc' : '#000'}
                      style={{ pointerEvents: 'none' }}
                    >
                      {label.length > w / 6 ? label.slice(0, Math.max(1, Math.floor(w / 6))) : label}
                    </text>
                  )}
                </g>
              );
            })}
          </g>

          {/* EVENTS lane */}
          <g transform={`translate(0,${laneTop(1)})`}>
            {incidents.map((inc) => {
              const xs = Math.max(0, x(inc.start));
              const xe = Math.min(width, x(inc.end));
              return (
                <rect
                  key={inc.id}
                  x={xs}
                  y={2}
                  width={Math.max(2, xe - xs)}
                  height={LANE_H - 4}
                  fill={INCIDENT_COLORS[inc.type] || '#888'}
                  opacity={0.85}
                  rx={1}
                >
                  <title>{`${inc.type}${inc.active ? ' (active)' : ''}`}</title>
                </rect>
              );
            })}
          </g>

          {/* SCRIPTS lane */}
          <g transform={`translate(0,${laneTop(2)})`}>
            {scripts.map((s) => {
              const xs = Math.max(0, x(s.start));
              const xe = Math.min(width, x(s.end));
              return (
                <rect
                  key={s.id}
                  x={xs}
                  y={2}
                  width={Math.max(3, xe - xs)}
                  height={LANE_H - 4}
                  fill={s.success === false ? '#f44336' : s.success ? '#4caf50' : '#9e9e9e'}
                  opacity={0.8}
                  rx={2}
                >
                  <title>{`${s.name} — ${s.success === false ? 'fail' : s.success ? 'pass' : 'running'}`}</title>
                </rect>
              );
            })}
          </g>

          {/* ZAPS lane — markers colored by transition (freeze / blackscreen) */}
          <g transform={`translate(0,${zapsLaneTop})`}>
            {zaps.map((z) => {
              const cx = x(z.t);
              if (cx < 0 || cx > width) return null;
              const color = z.transition === 'freeze' ? '#2196f3' : z.transition === 'blackscreen' ? '#bbbbbb' : '#9c27b0';
              const active = hoverZap?.id === z.id;
              return (
                <g key={z.id}>
                  <rect x={cx - 1.5} y={2} width={3} height={LANE_H - 4} fill={color} rx={1} />
                  {/* wide transparent hit target so a 3px marker is easy to hover */}
                  <rect
                    x={cx - 6}
                    y={0}
                    width={12}
                    height={LANE_H}
                    fill={active ? '#ffffff22' : 'transparent'}
                    style={{ cursor: 'pointer' }}
                    onMouseEnter={() => openZap(z)}
                    onMouseLeave={closeZapSoon}
                  />
                </g>
              );
            })}
          </g>

          {/* TRANSCRIPT presence lane — spans where audio transcript was found */}
          <g transform={`translate(0,${laneTop(4)})`}>
            {presenceSpans('transcript_available', TRANSCRIPT_PRESENT).map(([s, e], i) => {
              const xs = Math.max(0, x(s));
              const xe = Math.min(width, x(e));
              return (
                <rect key={i} x={xs} y={2} width={Math.max(2, xe - xs)} height={LANE_H - 4} fill="#26a69a" opacity={0.8} rx={1}>
                  <title>transcript available</title>
                </rect>
              );
            })}
          </g>

          {/* SUBTITLES presence lane — spans where subtitles were found */}
          <g transform={`translate(0,${laneTop(5)})`}>
            {presenceSpans('subtitle_availability', SUBTITLE_PRESENT).map(([s, e], i) => {
              const xs = Math.max(0, x(s));
              const xe = Math.min(width, x(e));
              return (
                <rect key={i} x={xs} y={2} width={Math.max(2, xe - xs)} height={LANE_H - 4} fill="#7e57c2" opacity={0.8} rx={1}>
                  <title>subtitles available</title>
                </rect>
              );
            })}
          </g>

          {/* hour axis labels */}
          {ticks.map((t, i) => (
            <text key={i} x={x(t)} y={totalH - 6} textAnchor="middle" fontSize={10} fill="#888">
              {new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </text>
          ))}

          {/* selected playhead (sought time) */}
          {selectedTime != null && x(selectedTime) >= 0 && x(selectedTime) <= width && (
            <line
              x1={x(selectedTime)}
              y1={0}
              x2={x(selectedTime)}
              y2={totalH - AXIS_H}
              stroke="#ffeb3b"
              strokeWidth={1.5}
            />
          )}

          {/* hover playhead */}
          {hoverX !== null && hoverX >= 0 && hoverX <= width && (
            <line x1={hoverX} y1={0} x2={hoverX} y2={totalH - AXIS_H} stroke="#fff" strokeWidth={1} opacity={0.5} />
          )}
        </svg>
        {hoverX !== null && hoverX >= 0 && hoverX <= width && (
          <Tooltip open title="" placement="bottom">
            <Box
              sx={{
                position: 'absolute',
                top: totalH - AXIS_H + 2,
                left: hoverX,
                transform: 'translateX(-50%)',
                bgcolor: 'background.paper',
                px: 0.5,
                fontSize: 10,
                color: 'text.secondary',
                pointerEvents: 'none',
                border: '1px solid',
                borderColor: 'divider',
                borderRadius: 0.5,
              }}
            >
              {new Date(t0 + (hoverX / width) * (t1 - t0)).toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit',
              })}
            </Box>
          </Tooltip>
        )}

        {/* Zap tooltip — interactive (so the report link is clickable). */}
        {hoverZap && x(hoverZap.t) >= 0 && x(hoverZap.t) <= width && (
          <Box
            onMouseEnter={() => openZap(hoverZap)}
            onMouseLeave={closeZapSoon}
            sx={{
              position: 'absolute',
              top: zapsLaneTop - 6,
              left: Math.min(Math.max(x(hoverZap.t), 70), width - 70),
              transform: 'translate(-50%, -100%)',
              bgcolor: 'background.paper',
              p: 1,
              minWidth: 160,
              fontSize: 11,
              color: 'text.primary',
              border: '1px solid',
              borderColor: 'divider',
              borderRadius: 1,
              boxShadow: 3,
              zIndex: 10,
            }}
          >
            <Box sx={{ fontWeight: 700, mb: 0.5 }}>
              Zap{hoverZap.key ? ` · ${hoverZap.key}` : ''}
              {hoverZap.channel ? ` → ${hoverZap.channel}` : ''}
            </Box>
            <Box sx={{ color: 'text.secondary' }}>
              {new Date(hoverZap.t).toLocaleString()}
            </Box>
            {hoverZap.transition && (
              <Box sx={{ color: 'text.secondary' }}>
                Transition: {hoverZap.transition}
                {hoverZap.durationMs != null ? ` · ${Math.round(hoverZap.durationMs)}ms` : ''}
              </Box>
            )}
            <Box sx={{ mt: 0.5 }}>
              {hoverZap.reportUrl ? (
                <a
                  href={hoverZap.reportUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: '#90caf9', textDecoration: 'underline' }}
                >
                  Open zap report ↗
                </a>
              ) : (
                <span style={{ color: '#777' }}>No report available</span>
              )}
            </Box>
          </Box>
        )}
      </Box>
    </Box>
  );
};

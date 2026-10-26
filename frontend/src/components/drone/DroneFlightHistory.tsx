import BlockIcon from '@mui/icons-material/Block';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import CloseIcon from '@mui/icons-material/Close';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import { Alert, Box, Dialog, DialogContent, DialogTitle, IconButton, Typography } from '@mui/material';
import React, { useEffect, useMemo, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useDroneCommandHistory } from '../../hooks/rec/useDroneCommandHistory';
import {
  describeCommand,
  flightLabel,
  formatDuration,
  groupFlights,
  outcomeOf,
  pathOf,
  sentNote,
  seriesOf,
  type DroneCommand,
  type DroneFlight,
  type PathPoint,
  type SeriesPoint,
} from './flightHistory';
import { TYPOGRAPHY } from '../../constants/typography';

type Palette = ReturnType<typeof useAgentChatPalette>;

const clock = (ts: string): string => {
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleTimeString([], { hour12: false });
};

const Outcome: React.FC<{ c: DroneCommand; P: Palette }> = ({ c, P }) => {
  const o = outcomeOf(c);
  if (o === 'ok') return <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, color: P.success }}><CheckCircleOutlineIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} /><span>OK</span></Box>;
  if (o === 'blocked') return <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, color: P.error, fontWeight: 700 }}><BlockIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} /><span>Blocked</span></Box>;
  return <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, color: P.warning }}><ErrorOutlineIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} /><span>Failed</span></Box>;
};

/** One small line chart: `points` over the flight's time, y from 0 to `yMax`; red ticks on the baseline where a command was blocked. */
const LineChart: React.FC<{ title: string; unit: string; points: SeriesPoint[]; yMax: number; blockedAt: number[]; t0: number; t1: number; P: Palette; testId: string }> = ({
  title, unit, points, yMax, blockedAt, t0, t1, P, testId,
}) => {
  const W = 320, H = 130, L = 34, R = 8, T = 10, B = 24;
  const span = Math.max(1, t1 - t0);
  const x = (t: number) => L + ((t - t0) / span) * (W - L - R);
  const y = (v: number) => T + (1 - Math.min(v, yMax) / yMax) * (H - T - B);
  const last = points[points.length - 1];
  return (
    <Box data-testid={testId} sx={{ flex: '1 1 260px', minWidth: 240 }}>
      <Typography variant="caption" sx={{ color: P.textSecondary, fontWeight: 600 }}>{title}</Typography>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={title}>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={L} x2={W - R} y1={y(yMax * f)} y2={y(yMax * f)} stroke={P.borderColor} strokeWidth={1} />
            <text x={L - 4} y={y(yMax * f) + 3} textAnchor="end" fontSize={10} fill={P.textSecondary}>{Math.round(yMax * f * 10) / 10}</text>
          </g>
        ))}
        {points.length > 1 && <polyline fill="none" stroke={P.accent} strokeWidth={2} points={points.map((p) => `${x(p.t)},${y(p.v)}`).join(' ')} />}
        {points.map((p, i) => <circle key={i} cx={x(p.t)} cy={y(p.v)} r={2.2} fill={P.accent} />)}
        {blockedAt.map((t, i) => <line key={i} data-testid="chart-blocked-tick" x1={x(t)} x2={x(t)} y1={H - B + 2} y2={H - B + 12} stroke={P.error} strokeWidth={2} />)}
        <text x={L} y={H - 2} fontSize={10} fill={P.textSecondary}>{clock(new Date(t0).toISOString())}</text>
        <text x={W - R} y={H - 2} textAnchor="end" fontSize={10} fill={P.textSecondary}>{clock(new Date(t1).toISOString())}</text>
        {last && <text x={W - R} y={T - 1} textAnchor="end" fontSize={10} fill={P.textPrimary}>{`${Math.round(last.v * 10) / 10} ${unit}`}</text>}
      </svg>
    </Box>
  );
};

/** Top-down path from the controller's dead-reckoned pose (cm): a line through the commands in order, green start, red where a command was blocked. */
const PathMap: React.FC<{ points: PathPoint[]; P: Palette }> = ({ points, P }) => {
  const W = 260, H = 200, pad = 18;
  if (points.length === 0) {
    return <Box data-testid="path-empty" sx={{ flex: '1 1 220px', minWidth: 200, color: P.textMuted, fontSize: TYPOGRAPHY.body.size, pt: 3 }}>No position recorded for this flight.</Box>;
  }
  const xs = points.map((p) => p.x), ys = points.map((p) => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const size = Math.max(maxX - minX, maxY - minY, 100);   // at least a metre, so a short hop is not blown up to the whole box
  const scale = Math.min(W - 2 * pad, H - 2 * pad) / size;
  const px = (v: number) => pad + (v - minX) * scale;
  const py = (v: number) => H - pad - (v - minY) * scale;      // y grows upwards on the map
  const first = points[0], last = points[points.length - 1];
  return (
    <Box data-testid="flight-path" sx={{ flex: '1 1 220px', minWidth: 200 }}>
      <Typography variant="caption" sx={{ color: P.textSecondary, fontWeight: 600 }}>Path from above (1 m = {Math.round(100 * scale)} px)</Typography>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Flight path seen from above">
        <rect x={0.5} y={0.5} width={W - 1} height={H - 1} fill="none" stroke={P.borderColor} />
        {points.length > 1 && <polyline fill="none" stroke={P.accent} strokeWidth={2} points={points.map((p) => `${px(p.x)},${py(p.y)}`).join(' ')} />}
        {points.filter((p) => p.outcome === 'blocked').map((p) => (
          <g key={p.seq} data-testid="path-blocked">
            <circle cx={px(p.x)} cy={py(p.y)} r={6} fill="none" stroke={P.error} strokeWidth={2} />
            <line x1={px(p.x) - 4} y1={py(p.y) - 4} x2={px(p.x) + 4} y2={py(p.y) + 4} stroke={P.error} strokeWidth={2} />
          </g>
        ))}
        <circle cx={px(first.x)} cy={py(first.y)} r={5} fill={P.success} />
        <circle cx={px(last.x)} cy={py(last.y)} r={4} fill="none" stroke={P.textPrimary} strokeWidth={2} />
        <text x={px(first.x) + 8} y={py(first.y) - 6} fontSize={10} fill={P.textSecondary}>start</text>
      </svg>
    </Box>
  );
};

const Stat: React.FC<{ label: string; value: string; P: Palette }> = ({ label, value, P }) => (
  <Box sx={{ minWidth: 90 }}>
    <Typography variant="caption" sx={{ color: P.textSecondary, display: 'block' }}>{label}</Typography>
    <Typography sx={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{value}</Typography>
  </Box>
);

export const FlightDetail: React.FC<{ flight: DroneFlight; P: Palette }> = ({ flight, P }) => {
  const series = useMemo(() => seriesOf(flight), [flight]);
  const points = useMemo(() => pathOf(flight), [flight]);
  const t0 = flight.start, t1 = Math.max(flight.end, flight.start + 1000);
  const blockedAt = flight.commands.filter((c) => c.blocked).map((c) => Date.parse(c.ts)).filter((t) => Number.isFinite(t));
  const maxH = Math.max(1.5, flight.maxHeightM ?? 0);
  return (
    <Box data-testid="flight-detail">
      <Box sx={{ display: 'flex', gap: 3, flexWrap: 'wrap', mb: 2 }}>
        <Stat P={P} label="Duration" value={formatDuration(flight.end - flight.start)} />
        <Stat P={P} label="Commands" value={String(flight.commands.length)} />
        <Stat P={P} label="Blocked" value={String(flight.blocked)} />
        <Stat P={P} label="Failed" value={String(flight.failed)} />
        <Stat P={P} label="Lowest battery" value={flight.minBattery == null ? '–' : `${flight.minBattery} %`} />
        <Stat P={P} label="Highest" value={flight.maxHeightM == null ? '–' : `${flight.maxHeightM.toFixed(1)} m`} />
      </Box>
      <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 2 }}>
        <LineChart testId="chart-battery" title="Battery" unit="%" points={series.battery} yMax={100} blockedAt={blockedAt} t0={t0} t1={t1} P={P} />
        <LineChart testId="chart-height" title="Height" unit="m" points={series.height} yMax={maxH} blockedAt={blockedAt} t0={t0} t1={t1} P={P} />
        <PathMap points={points} P={P} />
      </Box>
      <Box component="table" data-testid="command-timeline" sx={{ width: '100%', borderCollapse: 'collapse', fontSize: TYPOGRAPHY.body.size, '& th': { textAlign: 'left', color: P.textSecondary, fontWeight: 600, py: 0.5, pr: 1.5 }, '& td': { py: 0.5, pr: 1.5, borderTop: `1px solid ${P.borderColor}`, verticalAlign: 'top' } }}>
        <thead>
          <tr><th>Time</th><th>Command</th><th>Sent</th><th>Result</th><th>Took</th><th>Battery</th><th>Height</th></tr>
        </thead>
        <tbody>
          {flight.commands.map((c) => {
            const blocked = c.blocked;
            const note = sentNote(c);
            return (
              <Box component="tr" key={c.seq} data-testid="command-row" data-outcome={outcomeOf(c)} sx={blocked ? { bgcolor: `${P.error}1f` } : undefined}>
                <td style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>{clock(c.ts)}</td>
                <td style={{ fontFamily: 'monospace' }}>{describeCommand(c)}</td>
                <td style={{ fontFamily: 'monospace', color: note ? P.warning : P.textSecondary }}>
                  {note ? `${note} (shortened)` : c.sent ?? '–'}
                </td>
                <td>
                  <Outcome c={c} P={P} />
                  {(blocked || !c.success) && c.error && <Box sx={{ color: blocked ? P.error : P.textSecondary, fontSize: TYPOGRAPHY.caption.size }}>{c.error}</Box>}
                </td>
                <td style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>{c.duration_ms} ms</td>
                <td>{c.bat == null ? '–' : `${c.bat} %`}</td>
                <td>{c.h == null ? '–' : `${(c.h / 100).toFixed(1)} m`}</td>
              </Box>
            );
          })}
        </tbody>
      </Box>
    </Box>
  );
};

interface Props {
  open: boolean;
  onClose: () => void;
  hostName?: string;
  deviceId?: string;
  deviceName?: string;
  /** tests and demos: skip the server and show these */
  commands?: DroneCommand[];
}

/** The driving history of a Tello: flights on the left, then the selected flight's numbers, charts, path and command timeline. */
export const DroneFlightHistory: React.FC<Props> = ({ open, onClose, hostName, deviceId, deviceName, commands: provided }) => {
  const P = useAgentChatPalette();
  const live = useDroneCommandHistory(hostName, deviceId, open && !provided);
  const commands = provided ?? live.commands;
  const flights = useMemo(() => groupFlights(commands), [commands]);
  const [selected, setSelected] = useState<number | null>(null);
  useEffect(() => {
    if (flights.length > 0 && (selected === null || !flights.some((f) => f.flight === selected))) setSelected(flights[0].flight);
  }, [flights, selected]);
  const flight = flights.find((f) => f.flight === selected) ?? null;
  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth data-testid="drone-flight-history">
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span>Flight history{deviceName ? ` · ${deviceName}` : ''}</span>
        <IconButton aria-label="Close" onClick={onClose} size="small"><CloseIcon /></IconButton>
      </DialogTitle>
      <DialogContent>
        {!provided && live.error && <Alert severity="error" sx={{ mb: 2 }} data-testid="history-error">Could not read the flight history: {live.error}</Alert>}
        {flights.length === 0 ? (
          <Typography data-testid="history-empty" sx={{ color: P.textSecondary, py: 3 }}>
            {!provided && live.loading ? 'Loading…' : 'No commands recorded yet. The history starts when the controller sends its first command and is kept while vpt-host runs (and in the host\'s command log file).'}
          </Typography>
        ) : (
          <Box sx={{ display: 'flex', gap: 2.5, flexWrap: { xs: 'wrap', md: 'nowrap' } }}>
            <Box data-testid="flight-list" sx={{ width: { xs: '100%', md: 210 }, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 0.75 }}>
              {flights.map((f) => (
                <Box
                  key={f.flight}
                  component="button"
                  type="button"
                  data-testid="flight-item"
                  aria-pressed={f.flight === selected}
                  onClick={() => setSelected(f.flight)}
                  sx={{
                    textAlign: 'left', cursor: 'pointer', font: 'inherit', color: P.textPrimary, borderRadius: 1, p: 1,
                    bgcolor: f.flight === selected ? P.hoverBg : 'transparent',
                    border: `1px solid ${f.flight === selected ? P.accent : P.borderColor}`,
                  }}
                >
                  <Typography sx={{ fontWeight: 700, fontSize: TYPOGRAPHY.navbarItem.size }}>{flightLabel(f)}</Typography>
                  <Typography variant="caption" sx={{ color: P.textSecondary, display: 'block' }}>
                    {new Date(f.start).toLocaleTimeString([], { hour12: false })} · {formatDuration(f.end - f.start)}
                  </Typography>
                  <Typography variant="caption" sx={{ color: f.blocked ? P.error : P.textMuted, display: 'block', fontWeight: f.blocked ? 700 : 400 }}>
                    {f.commands.length} commands{f.blocked ? ` · ${f.blocked} blocked` : ''}
                  </Typography>
                </Box>
              ))}
            </Box>
            <Box sx={{ flex: 1, minWidth: 0 }}>{flight && <FlightDetail flight={flight} P={P} />}</Box>
          </Box>
        )}
      </DialogContent>
    </Dialog>
  );
};

export default DroneFlightHistory;

import { Box, Typography } from '@mui/material';
import React, { useEffect, useRef, useState } from 'react';

// palette: drawn on video/screenshot — like MonitoringOverlay this sits on top of a live stream, so
// the boxes and dots use saturated hex literals that stay readable on any image, and the panels are
// dark translucent cards in both app themes. Do NOT swap them for theme tokens.

import { AGENT_CHAT_PALETTE } from '../../constants/agentChatTheme';
import {
  MonitoringAnalysis,
  ProfileFocus,
  ProfileHudItem,
  ProfileObservation,
  ProfileTelemetry,
  ProfileUi,
  ProfileUiColour,
} from '../../types/pages/Monitoring_Types';
import { formatTimeWithMs } from '../../utils/dateUtils';
import { batteryBars, batteryColor } from '../rec/DroneBatteryBadge';
import { TYPOGRAPHY } from '../../constants/typography';

const BOX_COLOURS = ['#00e5ff', '#ffd400', '#ff4081', '#76ff03', '#ff9100', '#b388ff', '#40c4ff', '#ff5252'];

// Same label, same colour, across frames
const colourFor = (label: string): string => {
  let h = 0;
  for (let i = 0; i < label.length; i++) h = (h * 31 + label.charCodeAt(i)) >>> 0;
  return BOX_COLOURS[h % BOX_COLOURS.length];
};

// Colour names a profile's `ui` block may use, as readable-on-video hex
export const UI_HEX: Record<ProfileUiColour, string> = {
  green: '#2ecc71',
  red: '#ff5252',
  amber: '#ffb300',
  grey: '#9e9e9e',
  blue: '#42a5f5',
  purple: '#b388ff',
  white: '#f5f5f5',
  black: '#37474f',
  yellow: '#ffd400',
  brown: '#a1887f',
};
const VOTING_HEX = '#b388ff'; // a track that is still voting

/**
 * Gold is the colour of the item in the "Last checked" panel (BUG-0836). On a belt of 90 eggs the panel
 * names a verdict the operator cannot tie back to a picture, because every box is the colour of its own
 * class. One gold outline says "this one" without hunting.
 */
export const FOCUS_HEX = '#ffd400';

// How far the overlay advances its boxes for a moving object before it stops trusting the estimate.
// Beyond this the predicted position is further from the object than the last real one was, so the box
// fades out instead of gliding away from its egg.
export const MAX_LEAD_S = 0.8;

// Above this many boxes the per-box vote badges stop being readable, so only the focused item keeps one.
export const BADGE_ALL_UPTO = 12;

// Below this width of the player the right panel becomes a compact strip
export const COMPACT_BELOW_PX = 560;

// bbox is [x, y, w, h] in pixels of frame_size; values that are all <= 1 are fractions of the frame.
export const bboxToPercent = (
  bbox: [number, number, number, number],
  frameSize?: [number, number],
): { left: number; top: number; width: number; height: number } | null => {
  const [x, y, w, h] = bbox;
  if (![x, y, w, h].every((v) => Number.isFinite(v)) || w <= 0 || h <= 0) return null;
  const fractional = Math.max(x, y, w, h) <= 1;
  const [fw, fh] = fractional ? [1, 1] : frameSize && frameSize[0] > 0 && frameSize[1] > 0 ? frameSize : [0, 0];
  if (!fw || !fh) return null; // pixels without a frame size: cannot be placed
  return { left: (x / fw) * 100, top: (y / fh) * 100, width: (w / fw) * 100, height: (h / fh) * 100 };
};

const observationText = (o: ProfileObservation): string => {
  const attrs = o.attrs ? Object.values(o.attrs).join(' ') : '';
  const conf = typeof o.conf === 'number' ? ` ${Math.round(o.conf * 100)}%` : '';
  return `${attrs ? `${attrs} ` : ''}${o.label}${conf}`;
};

const formatKpi = (value: number | Record<string, number>): string =>
  typeof value === 'number'
    ? String(value)
    : Object.entries(value)
        .sort((a, b) => b[1] - a[1])
        .map(([k, v]) => `${k} ${v}`)
        .join(' · ');

const formatDuration = (ms: number): string => {
  const total = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
};

const capitalise = (s: string): string => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** Width of an element, kept current (ResizeObserver where it exists, the window size elsewhere). */
export const useElementWidth = (ref: React.RefObject<HTMLElement>): number => {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const read = () => setWidth(el.getBoundingClientRect().width);
    read();
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(read);
      ro.observe(el);
      return () => ro.disconnect();
    }
    window.addEventListener('resize', read);
    return () => window.removeEventListener('resize', read);
  }, [ref]);
  return width;
};

interface ProfileOverlayProps {
  analysis: MonitoringAnalysis;
  analysisTimestamp?: string;
  /** Resolves a file in the device's metadata folder to a URL (the "last checked" crop). */
  metadataUrl?: (fileName: string) => string;
  fpsIn?: number | null;
  fpsOut?: number | null;
  /**
   * ffmpeg-configured capture rate for this device (BUG-0575). Parsed on the host
   * from the live ffmpeg process cmdline (`-framerate N`). When set, the FPS line
   * shows this as the primary "in" value and tucks the measured value behind an
   * `(≈ …)` suffix when it differs, so the operator can tell "ffmpeg rate" from
   * "host is dropping frames".
   */
  fpsInConfigured?: number | null;
  /**
   * Fallback for the panel title when the current frame JSON has no `profile` yet
   * (BUG-0574). Comes from `host.system_stats.monitor_profiles[device_id]`.
   */
  profileName?: string;
  /**
   * The picture under this overlay IS the frame these boxes were measured on (BUG-0836). The boxes must then
   * be drawn exactly where they are: carrying them forward by velocity would move them off their objects,
   * because there is no lag left to correct.
   */
  frameLocked?: boolean;
  /**
   * The capture the analysis was computed from. When frame-locked it is drawn INSIDE the boxes' SVG, in the same
   * frame-pixel coordinates, so the picture and its boxes are scaled and letterboxed by one transform and cannot
   * land apart whatever the player's shape or the JPEG's size (BUG-0913).
   */
  frameUrl?: string | null;
}

// ---------------------------------------------------------------------------------------------
// Profiles with a `ui` block: drawn from the manifest, the same component for eggs, cars, ...
// ---------------------------------------------------------------------------------------------

const verdictColour = (ui: ProfileUi, verdict: string | null | undefined): string => {
  if (!verdict) return VOTING_HEX;
  const item = ui.counters?.items.find((i) => i.key === verdict);
  return item ? UI_HEX[item.colour] : UI_HEX.grey;
};

const labelOf = (ui: ProfileUi, key: string): string =>
  ui.counters?.items.find((i) => i.key === key)?.label ?? capitalise(key);

const UiBoxes: React.FC<{ analysis: MonitoringAnalysis; ui: ProfileUi; leadS: number; frameUrl?: string | null }> = ({
  analysis,
  ui,
  leadS,
  frameUrl,
}) => {
  const obs = analysis.observations ?? [];
  const fs = analysis.frame_size;
  const shape = ui.box?.shape ?? 'rect';
  const byVerdict = (ui.box?.colour_by ?? 'none') === 'verdict';
  const [fw, fh] = fs && fs[0] > 0 && fs[1] > 0 ? fs : [0, 0];
  if (!fw) return null;
  const stroke = Math.max(2, fw / 400);
  const font = Math.max(12, fw / 80);
  const focusId = analysis.focus?.track_id;
  // A badge on every box is unreadable once the scene has more than a handful of objects (90 eggs all
  // saying "3/3" is a wall of labels that carries no information). The focused item always keeps its
  // badge, and a small scene keeps them all so the voting is still legible.
  const badgeAll = ui.box?.badge === 'votes' && obs.length <= BADGE_ALL_UPTO;
  // The boxes are `leadS` old: advance each one along its own velocity and fade it out as the estimate ages.
  const stale = Math.max(0, Math.min(1, leadS / MAX_LEAD_S));
  const opacity = 1 - 0.85 * stale;
  return (
    <Box sx={{ position: 'absolute', inset: 0, zIndex: 15, pointerEvents: 'none' }}>
      {/* One SVG in frame pixels, letterboxed exactly like the video (object-fit: contain), so outlines and badges stay on the
          item whatever the player's shape */}
      <svg
        viewBox={`0 0 ${fw} ${fh}`}
        preserveAspectRatio="xMidYMid meet"
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
        data-testid="profile-shapes"
      >
        {frameUrl && (
          <image data-testid="analysed-frame-img" href={frameUrl} x={0} y={0} width={fw} height={fh} preserveAspectRatio="none" />
        )}
        {obs.map((o, i) => {
          const isFocus = focusId != null && o.track_id === focusId;
          const colour = isFocus ? FOCUS_HEX : byVerdict ? verdictColour(ui, o.verdict) : colourFor(o.label);
          const key = `${o.track_id ?? 'x'}-${i}`;
          // BUG-0836: hold the box on its object. The video under this overlay is newer than the frame the
          // boxes came from, so a moving object has moved on; v x age puts it back. Boxes without a
          // velocity (a stationary egg, or a tracker that reports no motion) stay where they were.
          const lead = o.v ? leadS : 0;
          const dx = o.v ? o.v[0] * lead : 0;
          const dy = o.v ? o.v[1] * lead : 0;
          const [rx, ry, rw, rh] = o.bbox;
          const x = rx + dx;
          const y = ry + dy;
          const w = rw;
          const h = rh;
          const isEllipse = shape === 'ellipse' && o.shape?.ellipse;
          const e = isEllipse
            ? [o.shape!.ellipse![0] + dx, o.shape!.ellipse![1] + dy, o.shape!.ellipse![2], o.shape!.ellipse![3], o.shape!.ellipse![4]]
            : null;
          const outline = isEllipse && e ? (
            <ellipse
              data-testid="profile-ellipse"
              cx={e[0]}
              cy={e[1]}
              rx={e[2] / 2}
              ry={e[3] / 2}
              transform={`rotate(${e[4]} ${e[0]} ${e[1]})`}
              fill="none"
              stroke={colour}
              strokeWidth={isFocus ? stroke * 1.8 : stroke}
              opacity={opacity}
            />
          ) : (
            <rect data-testid="profile-rect" x={x} y={y} width={w} height={h} fill="none" stroke={colour} strokeWidth={isFocus ? stroke * 1.8 : stroke} opacity={opacity} />
          );
          const badge = ui.box?.badge === 'votes' && o.votes && (badgeAll || isFocus) ? o.votes : null;
          const bw = font * (0.62 * (badge?.length ?? 0) + 1.2);
          const top = isEllipse && e ? e[1] - Math.max(e[2], e[3]) / 2 : y;
          const bx = isEllipse && e ? e[0] : x + w / 2;
          return (
            <g key={key} data-testid={isFocus ? 'profile-box-focus' : undefined}>
              {outline}
              {badge && (
                <g data-testid="profile-badge">
                  <rect x={bx - bw / 2} y={Math.max(0, top - font * 1.9)} width={bw} height={font * 1.5} rx={font * 0.3} fill={colour} />
                  <text
                    x={bx}
                    y={Math.max(0, top - font * 1.9) + font * 1.1}
                    textAnchor="middle"
                    fontSize={font}
                    fontWeight={700}
                    fill="#000000"
                    fontFamily="sans-serif"
                  >
                    {badge}
                  </text>
                </g>
              )}
            </g>
          );
        })}
      </svg>
    </Box>
  );
};

/**
 * How old the analysed frame is, in seconds, re-read on a tick so the boxes keep moving between two
 * JSONs (BUG-0836). The frame JSON lands in the browser up to one poll interval after the frame was
 * captured, and the video under it is later again; without this the overlay is a still picture of a
 * moment that has gone. 0 when the frame JSON carries no `captured_at` (older frames, tv_app).
 */
export const useOverlayAge = (capturedAt?: string): number => {
  const [age, setAge] = useState(() => ageOf(capturedAt));
  useEffect(() => {
    setAge(ageOf(capturedAt));
    if (!capturedAt) return undefined;
    const id = setInterval(() => setAge(ageOf(capturedAt)), 100);
    return () => clearInterval(id);
  }, [capturedAt]);
  return age;
};

const ageOf = (capturedAt?: string): number => {
  if (!capturedAt) return 0;
  const t = Date.parse(capturedAt);
  if (!Number.isFinite(t)) return 0;
  return Math.max(0, (Date.now() - t) / 1000);
};

const CounterDot: React.FC<{ colour: string }> = ({ colour }) => (
  <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: colour, flex: 'none' }} />
);

/**
 * The stat row: `Eggs 253 · Detections 82`, one row, never wrapping (BUG-0837).
 *
 * The two numbers answer different questions and the pair is the point, so they sit side by side:
 * **Eggs** is how many the profile has counted, **Detections** is how many the detector put a circle
 * on in this frame. A high first number with a low second one is the detector missing eggs that are
 * plainly on the belt — visible at a glance instead of having to compare two panels.
 *
 * `observations` is the length of the analysed frame's observation list, not a KPI: it is the honest
 * denominator, and it goes stale with the rest of the frame, which is the point.
 */
const Stats: React.FC<{ ui: ProfileUi; analysis: MonitoringAnalysis }> = ({ ui, analysis }) => {
  const items = ui.stats ?? [];
  if (items.length === 0) return null;
  const value = (s: NonNullable<ProfileUi['stats']>[number]) => {
    if (s.observations) return analysis.observations?.length;
    const v = analysis.kpis?.[s.kpi as string];
    return typeof v === 'number' ? v : undefined;
  };
  return (
    <Box data-testid="profile-stats" sx={{ mt: 1, display: 'flex', flexWrap: 'wrap', columnGap: 2.5, rowGap: 0.25 }}>
      {items.map((s) => {
        const v = value(s);
        return (
          <Box key={s.label} data-testid={`profile-stat-${s.label.toLowerCase().replace(/\s+/g, '-')}`} sx={{ display: 'flex', alignItems: 'baseline', columnGap: 0.6 }}>
            <Typography component="span" sx={{ fontSize: TYPOGRAPHY.pageTitle.size, fontWeight: 700, lineHeight: 1.1 }}>
              {typeof v === 'number' ? v : '–'}
            </Typography>
            <Typography component="span" variant="body2" sx={{ color: '#cccccc' }}>
              {s.label}
            </Typography>
          </Box>
        );
      })}
    </Box>
  );
};

/**
 * The counters, as ONE ROW PER CLASS with the count and its share side by side (BUG-0836).
 *
 * The grid this replaces was `1fr 1fr`, so three classes wrapped onto two lines with the second line
 * starting under the first: "Good 5 / Bad 679" then "Unverified 231" with its number pushed to the far
 * right, ~200 px from its label. Three short rows never wrap, and the share of the total next to each
 * count answers "how bad is this" without the operator doing the division.
 */
const Counters: React.FC<{
  ui: ProfileUi;
  counts: Record<string, number>;
  compact: boolean;
}> = ({ ui, counts, compact }) => {
  const items = ui.counters?.items ?? [];
  const total = items.reduce((a, i) => a + (counts?.[i.key] ?? 0), 0);
  const pct = (v: number) => (total > 0 ? `${((100 * v) / total).toFixed(1)}%` : '–');
  return (
    <Box data-testid="profile-counters" sx={{ mt: compact ? 1 : 1.5 }}>
      {/* the split at a glance: one bar, widths in proportion, before the numbers */}
      {total > 0 && (
        <Box
          data-testid="profile-counters-bar"
          sx={{ display: 'flex', height: 8, borderRadius: 1, overflow: 'hidden', mb: compact ? 0.75 : 1, background: 'rgba(255,255,255,0.15)' }}
        >
          {items.map((item) => {
            const v = counts?.[item.key] ?? 0;
            return v > 0 ? (
              <Box
                key={item.key}
                data-testid="profile-counter-bar"
                data-key={item.key}
                sx={{ width: `${(100 * v) / total}%`, background: UI_HEX[item.colour] }}
              />
            ) : null;
          })}
        </Box>
      )}
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: compact ? 0.25 : 0.5 }}>
        {items.map((item) => {
          const v = counts?.[item.key] ?? 0;
          return (
            <Box
              key={item.key}
              data-testid="profile-counter"
              data-key={item.key}
              sx={{ display: 'flex', alignItems: 'baseline', gap: 0.75, minWidth: 0, whiteSpace: 'nowrap' }}
            >
              <CounterDot colour={UI_HEX[item.colour]} />
              {!compact && (
                <Typography
                  variant="caption"
                  sx={{ color: '#dddddd', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}
                >
                  {item.label ?? capitalise(item.key)}
                </Typography>
              )}
              <Typography
                data-testid="profile-counter-value"
                sx={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: '#ffffff', lineHeight: 1.3 }}
              >
                {v}
              </Typography>
              <Typography
                data-testid="profile-counter-pct"
                sx={{
                  fontVariantNumeric: 'tabular-nums',
                  color: '#9a9a9a',
                  lineHeight: 1.3,
                  minWidth: compact ? 34 : 44,
                  textAlign: 'right',
                  fontSize: compact ? '0.62rem' : TYPOGRAPHY.caption.size,
                }}
              >
                {pct(v)}
              </Typography>
            </Box>
          );
        })}
      </Box>
      {!compact && total > 0 && (
        <Typography variant="caption" sx={{ display: 'block', mt: 0.75, color: '#8a8a8a' }}>
          {`of ${total} counted`}
        </Typography>
      )}
    </Box>
  );
};

const FocusPanel: React.FC<{
  ui: ProfileUi;
  focus: ProfileFocus;
  cropUrl: string | null;
}> = ({ ui, focus, cropUrl }) => {
  const fp = ui.focus_panel;
  if (!fp) return null;
  const classes = ui.counters?.items.map((i) => i.key).filter((k) => k !== 'unverified') ?? [];
  const probs = focus.probs ?? {};
  const keys = Array.from(new Set([...classes, ...Object.keys(probs)])).filter((k) => k in probs);
  const verdict = focus.verdict;
  const top = verdict ? probs[verdict] : undefined;
  return (
    <Box data-testid="profile-focus" sx={{ mt: 1.5, pt: 1.5, borderTop: '1px solid rgba(255,255,255,0.18)' }}>
      <Typography variant="caption" sx={{ color: '#bbbbbb' }}>
        {fp.title ?? 'Last checked'}
        {/* BUG-0836: the panel and the gold outline in the picture are the same object. Naming the colour
            here is what lets the operator find it among 90 identical eggs. */}
        <Box component="span" data-testid="profile-focus-colour" sx={{ color: FOCUS_HEX, ml: 0.75, fontWeight: 700 }}>
          ● gold in the picture
        </Box>
      </Typography>
      {fp.crop !== false && cropUrl && (
        <Box
          component="img"
          src={cropUrl}
          alt=""
          data-testid="profile-focus-crop"
          sx={{ display: 'block', width: '100%', maxHeight: 120, objectFit: 'contain', borderRadius: 0.5, mt: 0.5, background: '#000' }}
        />
      )}
      {verdict && (
        <Typography
          data-testid="profile-focus-verdict"
          sx={{ fontSize: TYPOGRAPHY.pageTitle.size, fontWeight: 700, lineHeight: 1.2, mt: 0.5, color: verdictColour(ui, focus.final ? verdict : null) }}
        >
          {`${labelOf(ui, verdict)}${typeof top === 'number' ? ` ${Math.round(top * 100)}%` : ''}`}
        </Typography>
      )}
      {verdict && (
        <Typography variant="caption" sx={{ color: '#bbbbbb', display: 'block' }}>
          {`check #${focus.check} · item #${focus.track_id}`}
        </Typography>
      )}
      {fp.probs !== false &&
        keys.map((k) => (
          <Box key={k} sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mt: 0.5 }} data-testid="profile-prob">
            <Typography variant="caption" sx={{ color: '#dddddd', width: 56, flex: 'none' }}>
              {labelOf(ui, k)}
            </Typography>
            <Box sx={{ flex: 1, height: 6, borderRadius: 3, background: 'rgba(255,255,255,0.15)', overflow: 'hidden' }}>
              <Box sx={{ width: `${Math.round((probs[k] ?? 0) * 100)}%`, height: '100%', background: verdictColour(ui, k) }} />
            </Box>
            <Typography variant="caption" sx={{ color: '#ffffff', width: 34, textAlign: 'right', flex: 'none' }}>
              {`${Math.round((probs[k] ?? 0) * 100)}%`}
            </Typography>
          </Box>
        ))}
    </Box>
  );
};

// ---------------------------------------------------------------------------------------------
// HUD: a vehicle's readings, top right (drone profile; a rover can use the same `ui.hud` list)
// ---------------------------------------------------------------------------------------------

const HUD_PALETTE = AGENT_CHAT_PALETTE; // drawn on video: the dark palette in both themes, like DroneTelemetryOverlay

const hudNumber = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** The text of one HUD field, or null while the vehicle does not report it (the row is then not drawn). */
export const hudValue = (item: ProfileHudItem, t: ProfileTelemetry): { text: string; warn: boolean; value: number | null } | null => {
  const v = hudNumber(t[item.key]);
  if (v === null) return null;
  const warn = (item.warn_above !== undefined && v > item.warn_above) || (item.warn_below !== undefined && v <= item.warn_below);
  switch (item.format ?? 'number') {
    case 'latlon': {
      const lon = item.key2 ? hudNumber(t[item.key2]) : null;
      return lon === null ? null : { text: `${v.toFixed(5)}, ${lon.toFixed(5)}`, warn: false, value: v };
    }
    case 'duration':
      return { text: formatDuration(v * 1000), warn, value: v };
    case 'battery':
      return { text: `${Math.round(v)}${item.unit ?? ''}`, warn, value: v };
    default:
      return { text: `${v.toFixed(item.decimals ?? 0)}${item.unit ? ` ${item.unit}` : ''}`, warn, value: v };
  }
};

const BatteryIcon: React.FC<{ pct: number; colour: string }> = ({ pct, colour }) => {
  const bars = batteryBars(pct);
  return (
    <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center' }} data-testid="hud-battery-icon" data-bars={bars}>
      <Box sx={{ width: 22, height: 11, border: `1.5px solid ${HUD_PALETTE.textSecondary}`, borderRadius: '2px', p: '1px', display: 'flex', gap: '1px', boxSizing: 'border-box' }}>
        {[0, 1, 2, 3].map((i) => (
          <Box key={i} sx={{ flex: 1, borderRadius: '1px', bgcolor: i < bars ? colour : 'transparent' }} />
        ))}
      </Box>
      <Box sx={{ width: 2, height: 5, bgcolor: HUD_PALETTE.textSecondary, borderRadius: '0 1px 1px 0' }} />
    </Box>
  );
};

const HudOverlay: React.FC<{ items: ProfileHudItem[]; telemetry: ProfileTelemetry | undefined; compact: boolean; incidents: string[] }> = ({
  items,
  telemetry,
  compact,
  incidents,
}) => {
  if (!telemetry) return null;
  const noTelemetry = telemetry.ok === false;
  const rows = noTelemetry ? [] : items.map((item) => ({ item, v: hudValue(item, telemetry) })).filter((r) => r.v !== null);
  return (
    <Box
      data-testid="profile-hud"
      data-compact={compact ? 'true' : 'false'}
      sx={{
        position: 'absolute',
        top: compact ? 6 : 12,
        right: compact ? 6 : 12,
        zIndex: 20,
        minWidth: compact ? 0 : 150,
        px: compact ? 0.75 : 1.5,
        py: compact ? 0.5 : 1,
        borderRadius: 1,
        bgcolor: `${HUD_PALETTE.background}d9`,
        color: HUD_PALETTE.textPrimary,
        fontVariantNumeric: 'tabular-nums',
        boxSizing: 'border-box',
      }}
    >
      {noTelemetry && (
        <Typography data-testid="hud-no-telemetry" sx={{ fontSize: compact ? '0.7rem' : '0.85rem', fontWeight: 700, color: HUD_PALETTE.warning, whiteSpace: 'nowrap' }}>
          NO TELEMETRY
        </Typography>
      )}
      {rows.map(({ item, v }) => {
        const colour = item.format === 'battery' && v!.value !== null ? batteryColor(v!.value, HUD_PALETTE) : v!.warn ? HUD_PALETTE.error : HUD_PALETTE.textPrimary;
        return (
          <Box key={`${item.key}-${item.label}`} data-testid="hud-row" data-key={item.key} sx={{ display: 'flex', alignItems: 'center', gap: compact ? 0.5 : 1, lineHeight: 1.5 }}>
            <Typography
              component="span"
              data-testid="hud-label"
              sx={{ fontSize: compact ? '0.6rem' : '0.75rem', fontWeight: 700, color: HUD_PALETTE.textSecondary, width: compact ? 26 : 52, flex: 'none' }}
            >
              {compact ? (item.short ?? item.label.slice(0, 3)).toUpperCase() : item.label}
            </Typography>
            {item.format === 'battery' && v!.value !== null && <BatteryIcon pct={v!.value} colour={colour} />}
            <Typography
              component="span"
              data-testid="hud-value"
              sx={{ fontSize: compact ? '0.72rem' : '0.85rem', fontWeight: 600, color: colour, ml: 'auto', whiteSpace: 'nowrap', textAlign: 'right' }}
            >
              {v!.text}
            </Typography>
          </Box>
        );
      })}
      {incidents.map((name) => (
        <Typography key={name} data-testid="hud-incident" sx={{ fontSize: compact ? '0.68rem' : '0.78rem', fontWeight: 700, color: HUD_PALETTE.error, mt: 0.25, whiteSpace: 'nowrap' }}>
          {name.replace(/_/g, ' ')}
        </Typography>
      ))}
    </Box>
  );
};

const FpsLine: React.FC<{ fpsIn?: number | null; fpsOut?: number | null; fpsInConfigured?: number | null }> = ({
  fpsIn,
  fpsOut,
  fpsInConfigured,
}) => {
  // BUG-0575: distinguish the rate ffmpeg was *told* to capture at (parsed on
  // the host from `-framerate N`) from the rate the monitor actually observes
  // (computed from capture sequence deltas in useMonitoring). The "in" value
  // used to be the measured one, which the operator found misleading — a stuck
  // monitor showed "FPS: in —" even though ffmpeg was happily running at 5 fps.
  // Primary = configured (what the host set), secondary = measured (what we
  // observe), so the operator can tell "ffmpeg rate" from "host is dropping frames".
  const inValue = fpsInConfigured ?? fpsIn;
  const measuredShown = fpsInConfigured != null && fpsIn != null && fpsIn !== fpsInConfigured;
  return (
    <Typography variant="body2" sx={{ color: '#cccccc' }} data-testid="profile-fps-line">
      FPS in{' '}
      <Box component="span" sx={{ color: inValue == null ? '#888888' : '#00ff00' }}>
        {inValue == null ? '—' : inValue}
      </Box>
      {measuredShown && (
        <Box component="span" data-testid="profile-fps-measured" sx={{ color: '#888888', ml: 0.75 }}>
          (≈ {fpsIn})
        </Box>
      )}
      {' · '}
      out{' '}
      <Box component="span" sx={{ color: fpsOut == null ? '#888888' : '#00ff00' }}>
        {fpsOut == null ? '—' : fpsOut}
      </Box>
    </Typography>
  );
};

const UiOverlay: React.FC<ProfileOverlayProps & { ui: ProfileUi }> = ({
  analysis,
  ui,
  metadataUrl,
  fpsIn,
  fpsOut,
  fpsInConfigured,
  frameLocked,
  frameUrl,
}) => {
  const rootRef = useRef<HTMLDivElement>(null);
  const width = useElementWidth(rootRef);
  const compact = width > 0 && width < COMPACT_BELOW_PX;
  // frame-locked: the picture is this frame, so there is nothing to correct and age must not move anything.
  // The hook is called either way (the toggle changes the value, not the number of hooks).
  const frameAgeS = useOverlayAge(analysis.captured_at);
  const leadS = frameLocked ? 0 : frameAgeS;
  // BUG-0913: the picture and its boxes change together. A new capture is preloaded off-screen and only then shown with
  // the analysis it belongs to, so a slow image never shows new boxes over the previous picture.
  const lockUrl = frameLocked ? frameUrl ?? null : null;
  const [shown, setShown] = useState<{ url: string | null; analysis: MonitoringAnalysis }>({ url: null, analysis });
  const pending = lockUrl && lockUrl !== shown.url ? lockUrl : null;
  const drawn = lockUrl ? shown : { url: null, analysis };
  const headlineValue = ui.headline ? analysis.kpis?.[ui.headline.kpi] : undefined;
  const counts = (ui.counters && analysis.kpis?.[ui.counters.kpi]) as Record<string, number> | undefined;
  const focus = ui.focus_panel ? analysis.focus : null;
  const cropUrl = focus?.crop && metadataUrl ? metadataUrl(focus.crop) : null;
  const activeIncidents = Object.entries(analysis.incidents ?? {}).filter(([, inc]) => inc.active);
  const badgeEvent = ui.state_badge ? analysis.events?.[ui.state_badge.event] : undefined;

  return (
    <Box
      ref={rootRef}
      data-testid="profile-overlay"
      data-compact={compact ? 'true' : 'false'}
      sx={{ position: 'absolute', inset: 0, zIndex: 15, pointerEvents: 'none' }}
    >
      <UiBoxes analysis={drawn.analysis} ui={ui} leadS={leadS} frameUrl={drawn.url} />
      {pending && (
        <img
          data-testid="analysed-frame-preload"
          src={pending}
          alt=""
          style={{ display: 'none' }}
          onLoad={() => setShown({ url: pending, analysis })}
          // a capture already drained from the hot folder: draw the boxes on the black backdrop rather than freeze
          onError={() => setShown({ url: null, analysis })}
        />
      )}

      {/* Top-left column: the title chip, and under it the state badge (the AD sign of ad_meter). One column, so the badge
          always starts below the chip whatever the chip's height (it sat at a fixed 52 px and covered the FPS line). */}
      <Box sx={{ position: 'absolute', top: 12, left: 12, zIndex: 20, display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 1 }}>
        {/* Title chip, top-left. The FPS line lives in a sibling Box (same backdrop) so the
            title's data-testid node carries only the title text — the test asserts that, and the
            two pieces of text are semantically distinct. */}
        <Box
          sx={{
            px: 1.25,
            py: 0.5,
            borderRadius: 1,
            backgroundColor: 'rgba(0, 0, 0, 0.7)',
            fontSize: compact ? '0.75rem' : '0.9rem',
            fontWeight: 600,
            color: '#ffffff',
          }}
        >
          <Typography component="span" data-testid="profile-title">{ui.title}</Typography>
          <Box component="span" data-testid="profile-fps" sx={{ display: 'block', fontSize: TYPOGRAPHY.caption.size, fontWeight: 400, color: '#cccccc', mt: 0.25 }}>
            {/* BUG-0575: prefer the ffmpeg-configured input rate; show the
                measured rate in parens when it differs so the operator can see
                "ffmpeg is set to 5 but only 3 are landing per second". */}
            FPS in {fpsInConfigured ?? fpsIn == null ? '—' : fpsInConfigured ?? fpsIn}
            {fpsInConfigured != null && fpsIn != null && fpsIn !== fpsInConfigured && (
              <Box component="span" data-testid="profile-fps-measured" sx={{ color: '#888888' }}>
                {' '}(≈ {fpsIn})
              </Box>
            )}
            {' · '}out {fpsOut == null ? '—' : fpsOut}
            {analysis.captured_at && !frameLocked && (
              // BUG-0836: how far behind the picture the boxes are. The boxes are advanced by this much
              // (see `useOverlayAge`), so it is the number that decides whether to trust them.
              <Box
                component="span"
                data-testid="profile-sync"
                sx={{ color: leadS > MAX_LEAD_S ? '#ff5252' : '#8a8a8a', ml: 0.75 }}
              >
                {` · sync ${Math.round(leadS * 1000)} ms`}
              </Box>
            )}
          </Box>
        </Box>

        {/* State badge under the title chip while its event is in progress (the AD sign of ad_meter), with how long it has lasted */}
        {ui.state_badge && badgeEvent && (
          <Typography
            data-testid="profile-state-badge"
            sx={{
              px: compact ? 1 : 1.75,
              py: compact ? 0.25 : 0.5,
              borderRadius: 1,
              fontSize: compact ? '0.9rem' : '1.6rem',
              fontWeight: 800,
              letterSpacing: 1,
              color: '#ffffff',
              backgroundColor: UI_HEX[ui.state_badge.colour ?? 'red'],
            }}
          >
            {`${ui.state_badge.label}${compact ? '' : ` ${formatDuration(badgeEvent.duration_ms)}`}`}
          </Typography>
        )}
      </Box>

      {/* Top-right HUD of a vehicle (battery, temperature, altitude, speed, GPS when it comes); its incidents are listed in it */}
      {ui.hud && <HudOverlay items={ui.hud} telemetry={analysis.telemetry} compact={compact} incidents={activeIncidents.map(([name]) => name)} />}

      {/* Right panel: full height, a quarter of the player; a narrow strip when the player is small. A profile that only has a HUD has none. */}
      {(ui.headline || ui.counters || focus || !ui.hud) && (
      <Box
        data-testid="profile-panel"
        sx={{
          position: 'absolute',
          top: 0,
          right: 0,
          bottom: 0,
          zIndex: 20,
          width: compact ? 76 : '25%',
          minWidth: compact ? 76 : 200,
          maxWidth: compact ? 76 : 300,
          p: compact ? 1 : 1.75,
          backgroundColor: 'rgba(0, 0, 0, 0.72)',
          color: '#ffffff',
          overflow: 'hidden',
          boxSizing: 'border-box',
        }}
      >
        {ui.headline && (
          <Box data-testid="profile-headline">
            <Typography sx={{ fontSize: compact ? '1.4rem' : '2.4rem', fontWeight: 700, lineHeight: 1.05 }}>
              {typeof headlineValue === 'number' ? `${headlineValue}${ui.headline.unit === '%' ? '%' : ''}` : '–'}
              {typeof headlineValue === 'number' && ui.headline.unit === 'min' && (
                <Typography component="span" sx={{ fontSize: compact ? '0.7rem' : '1rem', ml: 0.5 }}>
                  min
                </Typography>
              )}
            </Typography>
            {!compact && (
              <Typography variant="body2" sx={{ color: '#cccccc' }}>
                {ui.headline.label}
              </Typography>
            )}
          </Box>
        )}
        {ui.stats && <Stats ui={ui} analysis={analysis} />}
        {ui.counters && <Counters ui={ui} counts={counts ?? {}} compact={compact} />}
        {!compact && focus && <FocusPanel ui={ui} focus={focus} cropUrl={cropUrl} />}
        {!compact &&
          activeIncidents.map(([name, inc]) => (
            <Typography key={name} variant="body2" data-testid="profile-incident" sx={{ mt: 1, color: '#ff5252', fontWeight: 700 }}>
              {`${name}: ${inc.value}`}
            </Typography>
          ))}
      </Box>
      )}
    </Box>
  );
};

// ---------------------------------------------------------------------------------------------
// Profiles without a `ui` block: the generic overlay (boxes, events, KPIs)
// ---------------------------------------------------------------------------------------------

const GenericOverlay: React.FC<ProfileOverlayProps> = ({ analysis, analysisTimestamp, fpsIn, fpsOut, profileName, fpsInConfigured }) => {
  const observations = analysis.observations ?? [];
  const events = Object.entries(analysis.events ?? {});
  const kpis = Object.entries(analysis.kpis ?? {});
  // Title falls back to the device's configured profile (host.monitor_profiles[device_id])
  // when the JSON has not been populated yet (BUG-0574). Without this fallback the user
  // would see "Profile: <empty>" on a cold monitor and have no idea the device is configured
  // for `counting_cars` at all.
  const title = analysis.profile || profileName;
  // "Empty" = the monitor produced a JSON, but it carries nothing for this profile yet.
  // Captures may still be flowing (fpsOut > 0) while the profile analyzer hasn't run, or
  // the monitor may be stuck — show the user both possibilities with a hint to check.
  const monitorIdle = observations.length === 0 && events.length === 0 && kpis.length === 0;

  return (
    <>
      {/* Boxes: a layer over the whole video, one rectangle per observation */}
      <Box sx={{ position: 'absolute', inset: 0, zIndex: 15, pointerEvents: 'none' }}>
        {observations.map((o, i) => {
          const pos = bboxToPercent(o.bbox, analysis.frame_size);
          if (!pos) return null;
          const colour = colourFor(o.label);
          return (
            <Box
              key={`${o.track_id ?? 'x'}-${i}`}
              data-testid="profile-box"
              sx={{
                position: 'absolute',
                left: `${pos.left}%`,
                top: `${pos.top}%`,
                width: `${pos.width}%`,
                height: `${pos.height}%`,
                border: `2px solid ${colour}`,
                boxSizing: 'border-box',
              }}
            >
              <Typography
                component="span"
                sx={{
                  position: 'absolute',
                  bottom: '100%',
                  left: -2,
                  px: 0.5,
                  fontSize: TYPOGRAPHY.caption.size,
                  lineHeight: 1.4,
                  whiteSpace: 'nowrap',
                  color: '#000000',
                  backgroundColor: colour,
                }}
              >
                {o.track_id !== undefined ? `#${o.track_id} ` : ''}
                {observationText(o)}
                {o.votes ? ` · ${o.votes}` : ''}
              </Typography>
            </Box>
          );
        })}
      </Box>

      {/* Panel: profile, time, events in progress, KPIs */}
      <Box
        sx={{
          position: 'absolute',
          top: 16,
          left: 16,
          zIndex: 20,
          p: 2,
          borderRadius: 1,
          backgroundColor: 'rgba(0, 0, 0, 0.7)',
          pointerEvents: 'none',
          width: 400,
          whiteSpace: 'nowrap',
        }}
      >
        <Typography variant="body2" sx={{ color: title ? '#ffffff' : '#888888', fontWeight: 'bold', mb: 0.5 }}>
          {title || '—'}
          {analysisTimestamp && (
            <Typography component="span" variant="body2" sx={{ color: '#cccccc', ml: 1, fontFamily: 'monospace', fontWeight: 'normal' }}>
              {formatTimeWithMs(analysisTimestamp)}
            </Typography>
          )}
        </Typography>
        <FpsLine fpsIn={fpsIn} fpsOut={fpsOut} fpsInConfigured={fpsInConfigured} />
        {/* BUG-0574: when the monitor has produced nothing yet (cold start, model missing,
            vpt-monitor-img stuck), tell the operator what to check instead of leaving the
            panel empty and confusing. `fpsOut 0` plus `monitorIdle` is the canonical
            "monitor down" state; `fpsOut > 0` plus `monitorIdle` is "monitor running but
            profile analyzer hasn't run yet". */}
        {monitorIdle && (
          <Typography
            data-testid="profile-empty-state"
            variant="body2"
            sx={{ color: '#ffaa00', mt: 0.5 }}
          >
            {fpsOut == null || fpsOut === 0
              ? 'No data yet — check vpt-monitor-img on the host'
              : 'Monitor running, profile analyzer has not produced data yet'}
          </Typography>
        )}
        <Typography variant="body2" sx={{ color: '#cccccc' }}>
          Objects: <span style={{ color: '#ffffff' }}>{observations.length}</span>
        </Typography>
        {events.map(([name, ev]) => (
          <Typography key={name} variant="body2" sx={{ color: '#ffaa00' }}>
            {name}: {(ev.duration_ms / 1000).toFixed(1)}s
          </Typography>
        ))}
        {kpis.map(([name, value]) =>
          typeof value === 'number' ? (
            <Typography key={name} variant="body2" sx={{ color: '#cccccc', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {name}: <span style={{ color: '#ffffff' }}>{formatKpi(value)}</span>
            </Typography>
          ) : (
            // a counter per class; `unverified` (a track that left before it had enough votes) is shown apart in amber
            <Box key={name} sx={{ mt: 0.5 }}>
              <Typography variant="body2" sx={{ color: '#cccccc' }}>
                {name}
              </Typography>
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                {Object.entries(value)
                  .sort((a, b) => b[1] - a[1])
                  .map(([cls, n]) => (
                    <Typography
                      key={cls}
                      component="span"
                      data-testid="profile-counter"
                      sx={{
                        px: 0.75,
                        fontSize: TYPOGRAPHY.caption.size,
                        borderRadius: 0.5,
                        color: '#000000',
                        backgroundColor: cls === 'unverified' ? '#ffb300' : '#e0e0e0',
                      }}
                    >
                      {cls} {n}
                    </Typography>
                  ))}
              </Box>
            </Box>
          ),
        )}
        {Object.entries(analysis.incidents ?? {})
          .filter(([, inc]) => inc.active)
          .map(([name, inc]) => (
            <Typography key={name} variant="body2" sx={{ color: '#ff5252', fontWeight: 'bold' }}>
              {name}: {inc.value}
            </Typography>
          ))}
      </Box>
    </>
  );
};

export const ProfileOverlay: React.FC<ProfileOverlayProps> = (props) => {
  const ui = props.analysis.ui;
  return ui ? <UiOverlay {...props} ui={ui} /> : <GenericOverlay {...props} />;
};

export default ProfileOverlay;

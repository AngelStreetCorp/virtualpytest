import { Box } from '@mui/material';
import React, { useLayoutEffect, useRef, useState } from 'react';

import { AppIcon } from '../../../constants/icons';
import { TYPOGRAPHY } from '../../../constants/typography';
import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import {
  LOL_GAREN_FEET,
  LOL_MARKER_TTL_S,
  LolFrame,
  LolMarker,
  LolWorldUnit,
  LolZone,
} from '../../../types/game/LolOverlay_Types';

interface LolOverlayProps {
  zones: LolZone[];
  markers: LolMarker[];
  frame?: LolFrame;
  /** Shown instead of the drawing, e.g. "No live data". */
  message?: string | null;
  showLegend?: boolean;
  /** Perceived units (world block): dots with a health bar. */
  units?: LolWorldUnit[];
}

const DEFAULT_FRAME: LolFrame = { w: 1920, h: 1200 };

/**
 * Zones and input markers drawn over a video. The SVG viewBox is 1 x (h/w), so every contract
 * coordinate (x, y in 0..1, r relative to the width) is used as is; the box is the largest
 * rectangle of the frame's aspect ratio inside the parent (the video is letter-boxed the same way).
 */
export const LolOverlay: React.FC<LolOverlayProps> = ({ zones, markers, frame = DEFAULT_FRAME, message, showLegend = true, units = [] }) => {
  const P = useAgentChatPalette();
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [box, setBox] = useState<{ w: number; h: number } | null>(null);
  const ratio = frame.h / frame.w;
  const [hidden, setHidden] = useState<Partial<Record<LolZone['level'], boolean>>>({});

  useLayoutEffect(() => {
    const el = hostRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const update = () => {
      const { width, height } = el.getBoundingClientRect();
      const w = Math.min(width, height / ratio);
      setBox({ w, h: w * ratio });
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ratio]);

  const colourOf = (level: LolZone['level']) => (level === 'danger' ? P.error : level === 'caution' ? P.warning : P.success);
  const sw = 0.004; // stroke width in viewBox units (~0.4% of the width)
  const keys = markers.filter((m) => m.kind === 'key' && m.age < LOL_MARKER_TTL_S);

  return (
    <Box
      ref={hostRef}
      data-testid="lol-overlay"
      sx={{ position: 'absolute', inset: 0, pointerEvents: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 20 }}
    >
      {box && (
        <Box sx={{ position: 'relative', width: box.w, height: box.h, overflow: 'hidden' }}>
          <svg viewBox={`0 0 1 ${ratio}`} width={box.w} height={box.h} style={{ position: 'absolute', inset: 0 }}>
            {(['safe', 'caution', 'danger'] as const).map((level) => {
              const group = zones.filter((z) => z.level === level);
              if (hidden[level] || !group.length) return null;
              const c = colourOf(level);
              const circles = group.filter((z) => z.shape === 'circle' && z.x != null && z.y != null && z.r != null);
              return (
                <g key={level} data-level={level}>
                  <defs>
                    {/* Each circle's outline is shown only outside the other circles of its level: one union edge, not one ring per zone. */}
                    {circles.map((z, i) => (
                      <mask key={z.id} id={`lol-m-${level}-${i}`} maskUnits="userSpaceOnUse" x="0" y="0" width="1" height={ratio}>
                        <rect x="0" y="0" width="1" height={ratio} fill="white" />
                        {circles.filter((_, j) => j !== i).map((o) => (
                          <circle key={o.id} cx={o.x} cy={(o.y as number) * ratio} r={o.r} fill="black" />
                        ))}
                      </mask>
                    ))}
                  </defs>
                  {level === 'danger' && (
                    <g opacity={0.1}>
                      {circles.map((z) => <circle key={z.id} cx={z.x} cy={(z.y as number) * ratio} r={z.r} fill={c} />)}
                    </g>
                  )}
                  {circles.map((z, i) => (
                    <circle key={z.id} cx={z.x} cy={(z.y as number) * ratio} r={z.r} fill="none" stroke={c} strokeWidth={2}
                      vectorEffect="non-scaling-stroke" mask={`url(#lol-m-${level}-${i})`} />
                  ))}
                  {group.filter((z) => z.shape === 'polygon' && z.points?.length).map((z) => (
                    <polygon key={z.id} points={(z.points as [number, number][]).map(([x, y]) => `${x},${y * ratio}`).join(' ')}
                      fill={level === 'danger' ? c : 'none'} fillOpacity={0.1} stroke={c} strokeWidth={2} vectorEffect="non-scaling-stroke" />
                  ))}
                </g>
              );
            })}
            {units.map((u) => {
              const enemy = u.kind.startsWith('enemy');
              const c = enemy ? P.error : P.success;
              const cx = u.x;
              const cy = u.y * ratio;
              const big = u.kind.endsWith('champion') || u.kind.endsWith('turret');
              const r = big ? 0.009 : 0.006;
              const frac = Math.max(0, Math.min(1, u.hp_frac ?? 0));
              return (
                <g key={u.id} data-unit={u.kind}>
                  {u.in_attack_range && <circle cx={cx} cy={cy} r={r + 0.006} fill="none" stroke={c} strokeWidth={sw * 0.8} vectorEffect="non-scaling-stroke" />}
                  {u.selected && <circle cx={cx} cy={cy} r={r + 0.011} fill="none" stroke={P.accent} strokeWidth={sw * 0.8} vectorEffect="non-scaling-stroke" />}
                  <circle cx={cx} cy={cy} r={r} fill={c} stroke={P.sidebarBgSolid} strokeWidth={sw * 0.5} vectorEffect="non-scaling-stroke" />
                  {u.hp_frac != null && (
                    <g>
                      <rect x={cx - 0.012} y={cy - r - 0.011} width={0.024} height={0.004} fill={P.sidebarBgSolid} />
                      <rect x={cx - 0.012} y={cy - r - 0.011} width={0.024 * frac} height={0.004} fill={c} />
                    </g>
                  )}
                </g>
              );
            })}
            {markers.map((m, i) => {
              const fade = Math.max(0, 1 - m.age / LOL_MARKER_TTL_S);
              if (fade <= 0 || m.x == null || m.y == null) return null;
              const cx = m.x;
              const cy = m.y * ratio;
              if (m.kind === 'right_click') {
                return <circle key={i} cx={cx} cy={cy} r={0.012 + 0.02 * (1 - fade)} fill="none" stroke={P.accent} strokeWidth={sw * 1.5} opacity={fade} />;
              }
              if (m.kind === 'left_click') {
                return <circle key={i} cx={cx} cy={cy} r={0.008} fill={P.accent} opacity={fade} />;
              }
              if (m.kind === 'minimap') {
                return (
                  <g key={i} opacity={fade}>
                    <circle cx={cx} cy={cy} r={0.014} fill="none" stroke={P.accentText} strokeWidth={sw} />
                    <circle cx={cx} cy={cy} r={0.004} fill={P.accentText} />
                  </g>
                );
              }
              if (m.kind === 'move') {
                return <circle key={i} cx={cx} cy={cy} r={0.005} fill={P.textSecondary} opacity={fade * 0.8} />;
              }
              return null;
            })}
            {keys.map((m, i) => {
              const fade = Math.max(0, 1 - m.age / LOL_MARKER_TTL_S);
              const bx = LOL_GAREN_FEET[0] + (i - (keys.length - 1) / 2) * 0.03;
              const by = (LOL_GAREN_FEET[1] - 0.09) * ratio;
              return (
                <g key={`k${i}`} opacity={fade}>
                  <rect x={bx - 0.013} y={by - 0.013} width={0.026} height={0.026} rx={0.005} fill={P.sidebarBgSolid} stroke={P.accent} strokeWidth={sw * 0.8} />
                  <text x={bx} y={by + 0.006} textAnchor="middle" fontSize={0.017} fontWeight={700} fill={P.textPrimary}>{m.key}</text>
                </g>
              );
            })}
          </svg>
          {showLegend && (
            <Box
              sx={{
                position: 'absolute', left: 8, top: 8, pointerEvents: 'auto', display: 'flex', gap: 1.5, px: 1, py: 0.5, borderRadius: 1,
                bgcolor: P.sidebarBgSolid, border: `1px solid ${P.borderColor}`, color: P.textSecondary, fontSize: TYPOGRAPHY.caption.size,
              }}
            >
              {([['danger', P.error], ['caution', P.warning], ['safe', P.success]] as const).map(([label, c]) => (
                <Box
                  key={label}
                  component="button"
                  type="button"
                  aria-pressed={!hidden[label]}
                  title={hidden[label] ? `Show ${label} zones` : `Hide ${label} zones`}
                  onClick={() => setHidden((h) => ({ ...h, [label]: !h[label] }))}
                  sx={{
                    display: 'flex', alignItems: 'center', gap: 0.5, p: 0, border: 0, bgcolor: 'transparent', cursor: 'pointer',
                    font: 'inherit', color: hidden[label] ? P.textMuted : P.textSecondary, textDecoration: hidden[label] ? 'line-through' : 'none',
                  }}
                >
                  <Box sx={{ width: 10, height: 10, borderRadius: '50%', border: `2px solid ${hidden[label] ? P.textMuted : c}` }} />
                  {label}
                </Box>
              ))}
            </Box>
          )}
        </Box>
      )}
      {message && (
        <Box
          sx={{
            position: 'absolute', top: 8, left: '50%', transform: 'translateX(-50%)', display: 'flex', alignItems: 'center', gap: 0.75,
            px: 1.25, py: 0.5, borderRadius: 1, bgcolor: P.sidebarBgSolid, border: `1px solid ${P.borderColor}`, color: P.textSecondary, fontSize: TYPOGRAPHY.caption.size,
          }}
        >
          <AppIcon name="info" />
          {message}
        </Box>
      )}
    </Box>
  );
};

import { Box, CircularProgress, Tooltip, Typography } from '@mui/material';
import React, { useMemo, useState } from 'react';

import { AVQFrame, AVQFrameMeta, useAVQFrames } from '../hooks/useAVQFrames';

interface AVQFrameStripProps {
  host: any;
  deviceId: string;
  /** Center the strip on the frame nearest this epoch (null = nothing selected yet). */
  centerEpoch: number | null;
  /** The page's selected epoch — that tile gets the highlighted ring. */
  selectedEpoch: number | null;
  /** Click a tile → re-select that moment (drives main frame + right panel + playhead). */
  onSelect: (epochMs: number) => void;
}

const HALF = 2; // 2 each side of center → 5 tiles ("2 left, 2 right")
const COUNT = HALF * 2 + 1;
const GAP = 8;
const TILE_MAX = 240;
const TILE_MIN = 120;
const CHUNK_MS = 600_000; // 10-min metadata chunk
const NEAR_S = 10; // load the adjacent chunk when within this many seconds of an edge

// Per-frame defect → border color (mirrors AVQTimeline INCIDENT_COLORS; clean = green).
const borderColor = (m: AVQFrameMeta): string =>
  m.blackscreen ? '#000000'
    : m.freeze ? '#f44336'
    : m.macroblocks ? '#9c27b0'
    : m.audio === false ? '#ff9800'
    : '#4caf50';

const defectLabel = (m: AVQFrameMeta): string | null =>
  m.blackscreen ? `BLACK ${Math.round(m.blackscreen_percentage)}%`
    : m.freeze ? 'FREEZE'
    : m.macroblocks ? 'MACRO'
    : m.audio === false ? 'NO AUDIO'
    : null;

const hhmmss = (epochMs: number) => new Date(epochMs).toLocaleTimeString([], { hour12: false });

/**
 * Horizontal context filmstrip around the selected frame (1 fps stills): always 2
 * tiles each side (5 total), centered on the selected frame which is ringed while
 * the rest are dimmed. Tiles size to fill the panel width (no scrollbar). Loads the
 * adjacent 10-min chunk when the center sits near a window edge, so the before/after
 * never clips at a chunk boundary. Click a tile to re-center.
 */
export const AVQFrameStrip: React.FC<AVQFrameStripProps> = ({
  host,
  deviceId,
  centerEpoch,
  selectedEpoch,
  onSelect,
}) => {
  // Load the center chunk, plus the adjacent chunk only when near an edge (so ±2
  // can reach into the neighbouring 10-min window). Hooks are called unconditionally;
  // a null target makes useAVQFrames return [] without fetching.
  const secInChunk = centerEpoch != null
    ? (new Date(centerEpoch).getMinutes() * 60 + new Date(centerEpoch).getSeconds()) % 600
    : -1;
  const prevEpoch = centerEpoch != null && secInChunk >= 0 && secInChunk < NEAR_S ? centerEpoch - CHUNK_MS : null;
  const nextEpoch = centerEpoch != null && secInChunk > 600 - NEAR_S ? centerEpoch + CHUNK_MS : null;

  const c = useAVQFrames(host, deviceId, centerEpoch);
  const p = useAVQFrames(host, deviceId, prevEpoch);
  const n = useAVQFrames(host, deviceId, nextEpoch);

  const frames = useMemo<AVQFrame[]>(() => {
    const byKey = new Map<number, AVQFrame>();
    for (const f of [...p.frames, ...c.frames, ...n.frames]) byKey.set(f.seq, f);
    return Array.from(byKey.values()).sort((a, b) => a.epochMs - b.epochMs);
  }, [p.frames, c.frames, n.frames]);

  // Measure available width → size tiles so exactly COUNT fill the row (no scrollbar).
  const wrapRef = React.useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  React.useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const update = () => setWidth(el.clientWidth);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const tileW = width > 0
    ? Math.min(TILE_MAX, Math.max(TILE_MIN, Math.floor((width - (COUNT - 1) * GAP) / COUNT)))
    : 200;
  const tileH = Math.round((tileW * 9) / 16);

  const centerIdx = centerEpoch != null && frames.length
    ? frames.reduce((best, f, i) => (Math.abs(f.epochMs - centerEpoch) < Math.abs(frames[best].epochMs - centerEpoch) ? i : best), 0)
    : -1;
  const strip = centerIdx >= 0 ? frames.slice(Math.max(0, centerIdx - HALF), centerIdx + HALF + 1) : [];

  let body: React.ReactNode;
  if (centerEpoch == null) {
    body = (
      <Typography variant="caption" color="text.secondary">
        Select a frame on the timeline to see the surrounding frames.
      </Typography>
    );
  } else if (c.loading && strip.length === 0) {
    body = <CircularProgress size={18} />;
  } else if (strip.length === 0) {
    body = (
      <Typography variant="caption" color="text.secondary">
        No archived stills for this time. Enable capture archiving (--keep-captures true) on the
        host to keep 24h of stills.
      </Typography>
    );
  } else {
    body = (
      <Box sx={{ display: 'flex', gap: `${GAP}px`, justifyContent: 'center', overflow: 'hidden' }}>
        {strip.map((f) => {
          const isSelected = selectedEpoch != null && Math.abs(f.epochMs - selectedEpoch) < 500;
          const bc = borderColor(f.meta);
          const label = defectLabel(f.meta);
          return (
            <Box
              key={f.seq}
              onClick={() => onSelect(f.epochMs)}
              sx={{
                flex: '0 0 auto',
                cursor: 'pointer',
                textAlign: 'center',
                opacity: isSelected ? 1 : 0.55,
                transition: 'opacity 0.15s',
                '&:hover': { opacity: 1 },
              }}
            >
              <Tooltip title={`${hhmmss(f.epochMs)}${label ? ` · ${label}` : ' · clean'}`}>
                <Box
                  sx={{
                    width: tileW,
                    height: tileH,
                    bgcolor: 'black',
                    borderRadius: 0.5,
                    overflow: 'hidden',
                    border: isSelected ? '4px solid' : '3px solid',
                    borderColor: isSelected ? '#ffeb3b' : bc,
                    boxShadow: isSelected ? '0 0 0 2px #ffeb3b' : 'none',
                    boxSizing: 'border-box',
                  }}
                >
                  <img
                    src={f.imageUrl}
                    alt={`frame ${f.seq}`}
                    draggable={false}
                    style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                  />
                </Box>
              </Tooltip>
              <Typography
                variant="caption"
                sx={{
                  display: 'block',
                  fontSize: '0.7rem',
                  color: isSelected ? '#ffeb3b' : label ? bc : 'text.secondary',
                  fontWeight: isSelected || label ? 700 : 400,
                  lineHeight: 1.5,
                }}
              >
                {hhmmss(f.epochMs)}
                {label ? ` · ${label}` : ''}
              </Typography>
            </Box>
          );
        })}
      </Box>
    );
  }

  return <Box ref={wrapRef} sx={{ width: '100%' }}>{body}</Box>;
};

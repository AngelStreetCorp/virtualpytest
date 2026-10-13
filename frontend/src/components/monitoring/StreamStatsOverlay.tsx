import RefreshIcon from '@mui/icons-material/Refresh';
import { Box, CircularProgress, IconButton, Typography } from '@mui/material';
import React, { useEffect, useMemo, useState } from 'react';

import type { Host } from '../../types/common/Host_Types';
import type { LiveStreamStats } from '../video/hooks/useLiveStreamStats';

import { useHostSnapshot } from './hooks/useHostSnapshot';
import {
  OVERLAY_COLORS,
  RESOURCE_ERROR_PERCENT,
  RESOURCE_WARN_PERCENT,
  SERVICE_LOOKS,
  STALE_AFTER_SECONDS,
} from './StreamStatsOverlay.constants';

/** Host load has no defensible threshold — we don't know the core count. Neutral by design. */
const loadTone = () => OVERLAY_COLORS.muted;

const percentTone = (value?: number): string => {
  if (typeof value !== 'number') return OVERLAY_COLORS.dim;
  if (value >= RESOURCE_ERROR_PERCENT) return OVERLAY_COLORS.error;
  if (value >= RESOURCE_WARN_PERCENT) return OVERLAY_COLORS.warn;
  return OVERLAY_COLORS.ok;
};

const formatAge = (seconds: number): string =>
  seconds < 60 ? `${Math.round(seconds)}s` : `${Math.floor(seconds / 60)}m`;

const Row: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <Box sx={{ display: 'flex', alignItems: 'baseline', mb: 0.25, whiteSpace: 'nowrap' }}>
    <Typography component="span" variant="body2" sx={{ color: OVERLAY_COLORS.text, mr: 1 }}>
      {label}:
    </Typography>
    <Typography
      component="span"
      variant="body2"
      sx={{ color: OVERLAY_COLORS.muted, fontFamily: 'monospace', fontSize: '0.78rem' }}
    >
      {children}
    </Typography>
  </Box>
);

interface StreamStatsOverlayProps {
  /** The host being watched. The overlay fetches its current stats from the host's own server. */
  host?: Host;
  /** Live playback metrics. Absent on the VNC path, which has no <video> to measure. */
  live?: LiveStreamStats | null;
}

export const StreamStatsOverlay: React.FC<StreamStatsOverlayProps> = ({ host, live }) => {
  // One read on open, then only on the refresh button — no polling.
  const { snapshot, fetchedAt, loading, error, refresh } = useHostSnapshot(host);

  // Ticks the "checked Xs ago" label only; staleness is judged at fetch time below.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const stats = snapshot?.system_stats;
  const services = useMemo(
    () => stats?.service_health?.services ?? [],
    [stats?.service_health?.services],
  );
  const watched = useMemo(
    () =>
      ['vpt-stream', 'vpt-monitor'].map(
        (name) => services.find((s) => s.name === name || s.resolved_name === name) ?? null,
      ),
    [services],
  );

  // Heartbeat age as of the fetch, not as of now: the data is a snapshot, so letting it
  // age with the clock would flag a healthy host "stale" 90s after every refresh.
  const heartbeatAge =
    fetchedAt !== null && typeof snapshot?.last_seen === 'number' && snapshot.last_seen > 0
      ? fetchedAt / 1000 - snapshot.last_seen
      : null;
  const heartbeatKnown = heartbeatAge !== null;
  const heartbeatStale = !heartbeatKnown || Math.max(0, heartbeatAge) > STALE_AFTER_SECONDS;
  const checkedAgo = fetchedAt !== null ? (now - fetchedAt) / 1000 : null;

  const hasLive = Boolean(live && (live.fps !== null || live.latencySeconds !== null));
  const hasHost = Boolean(host);
  // Nothing honest to say yet — an empty box on the video is just clutter.
  if (!hasLive && !hasHost) return null;

  const latencyTone =
    live?.latencySeconds == null
      ? OVERLAY_COLORS.dim
      : live.latencySeconds > 6
        ? OVERLAY_COLORS.error
        : live.latencySeconds > 3
          ? OVERLAY_COLORS.warn
          : OVERLAY_COLORS.ok;

  return (
    <Box
      sx={{
        position: 'absolute',
        bottom: 16,
        left: 16,
        zIndex: 30,
        p: 1.25,
        borderRadius: 1,
        backgroundColor: 'rgba(0, 0, 0, 0.7)',
        pointerEvents: 'none',
        // Fixed width: the box must not resize between samples, or the number that
        // matters most is the one that moves.
        width: 300,
        whiteSpace: 'nowrap',
      }}
    >
      {hasLive && (
        <>
          <Typography
            variant="body2"
            sx={{ color: OVERLAY_COLORS.text, fontSize: '0.7rem', letterSpacing: 0.4, mb: 0.25 }}
          >
            STREAM · live
          </Typography>
          <Row label="FPS">
            <Box component="span" sx={{ color: live?.fps === null ? OVERLAY_COLORS.dim : OVERLAY_COLORS.ok }}>
              {live?.fps === null ? '—' : live?.fps}
            </Box>
            {live?.droppedFps != null && live.droppedFps > 0 && (
              <Box component="span" sx={{ color: OVERLAY_COLORS.warn, ml: 1 }}>
                {live.droppedFps} drop
              </Box>
            )}
          </Row>
          {live?.latencySeconds != null && (
            <Row label="Latency">
              <Box component="span" sx={{ color: latencyTone }}>
                {live.latencySeconds.toFixed(1)}s
              </Box>
              <Box component="span" sx={{ color: OVERLAY_COLORS.dim, ml: 1 }}>
                behind live
              </Box>
            </Row>
          )}
        </>
      )}

      {hasHost && (
        <>
          {/* Vertical break between the two cadences, so the live block is never
              mistaken for the heartbeat block directly above or below it. */}
          {hasLive && <Box sx={{ height: 6 }} />}
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.25 }}>
            <Typography
              variant="body2"
              sx={{
                color: snapshot && heartbeatStale ? OVERLAY_COLORS.warn : OVERLAY_COLORS.text,
                fontSize: '0.7rem',
                letterSpacing: 0.4,
                flex: 1,
              }}
            >
              HOST ·{' '}
              {error
                ? 'fetch failed'
                : !snapshot
                  ? 'checking…'
                  : heartbeatStale
                    ? heartbeatKnown
                      ? 'no recent heartbeat'
                      : 'unknown age'
                    : `${formatAge(Math.max(0, heartbeatAge!))} old`}
              {checkedAgo !== null && (
                <Box component="span" sx={{ color: OVERLAY_COLORS.dim }}>
                  {' '}· checked {formatAge(checkedAgo)} ago
                </Box>
              )}
            </Typography>
            {/* The box ignores the pointer so the video stays clickable; only this button takes it. */}
            <IconButton
              size="small"
              onClick={refresh}
              disabled={loading}
              aria-label="Refresh host stats"
              sx={{ pointerEvents: 'auto', p: 0.25, color: OVERLAY_COLORS.muted }}
            >
              {loading ? (
                <CircularProgress size={12} sx={{ color: OVERLAY_COLORS.muted }} />
              ) : (
                <RefreshIcon sx={{ fontSize: 14 }} />
              )}
            </IconButton>
          </Box>

          {heartbeatStale ? (
            <Typography
              variant="body2"
              sx={{ color: OVERLAY_COLORS.dim, fontFamily: 'monospace', fontSize: '0.78rem' }}
            >
              —
            </Typography>
          ) : (
            <>
              <Row label="CPU/RAM">
                <Box component="span" sx={{ color: percentTone(stats?.cpu_percent) }}>
                  {stats?.cpu_percent !== undefined ? `${Math.round(stats.cpu_percent)}%` : '—'}
                </Box>
                {' · '}
                <Box component="span" sx={{ color: percentTone(stats?.memory_percent) }}>
                  {stats?.memory_percent !== undefined ? `${Math.round(stats.memory_percent)}%` : '—'}
                </Box>
              </Row>
              <Row label="Load">
                <Box component="span" sx={{ color: loadTone() }}>
                  {stats?.load_average_1m !== undefined ? stats.load_average_1m.toFixed(2) : '—'}
                </Box>
                {typeof stats?.disk_write_mb_per_sec === 'number' && (
                  <>
                    {' · '}
                    <Box component="span" sx={{ color: OVERLAY_COLORS.muted }}>
                      {stats.disk_write_mb_per_sec.toFixed(1)} MB/s
                    </Box>
                  </>
                )}
              </Row>
            </>
          )}

          <Box sx={{ display: 'flex', gap: 1.5, mt: 0.5 }}>
            {(['stream', 'monitor'] as const).map((unit, index) => {
              const service = watched[index];
              const look = service ? SERVICE_LOOKS[service.status] ?? SERVICE_LOOKS.unknown : null;
              return (
                <Typography
                  key={unit}
                  variant="body2"
                  sx={{ color: OVERLAY_COLORS.text, fontSize: '0.78rem' }}
                >
                  {unit}{' '}
                  <Box component="span" sx={{ color: look?.color ?? OVERLAY_COLORS.dim, fontFamily: 'monospace' }}>
                    {heartbeatStale ? '—' : look?.text ?? '?'}
                  </Box>
                </Typography>
              );
            })}
          </Box>
        </>
      )}
    </Box>
  );
};

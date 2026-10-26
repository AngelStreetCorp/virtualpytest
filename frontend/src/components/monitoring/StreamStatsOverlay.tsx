import RefreshIcon from '@mui/icons-material/Refresh';
import { Box, CircularProgress, IconButton, Tooltip, Typography } from '@mui/material';
import React, { useEffect, useMemo, useState } from 'react';

import { useWebRTCStats } from '../../hooks/controller/useWebRTCStats';
import type { Host } from '../../types/common/Host_Types';
import type { LiveStreamStats } from '../video/hooks/useLiveStreamStats';

import { useHostSnapshot } from './hooks/useHostSnapshot';
import {
  FREEZE_ERROR_PERCENT,
  IMG_AGE_ERROR_MS,
  IMG_AGE_WARN_MS,
  FREEZE_WARN_PERCENT,
  JITTER_ERROR_MS,
  JITTER_WARN_MS,
  NACK_ERROR_PERCENT,
  NACK_WARN_PERCENT,
  OVERLAY_COLORS,
  OVERLAY_FONT,
  RESOURCE_ERROR_PERCENT,
  RESOURCE_WARN_PERCENT,
  SERVICE_LOOKS,
  STALE_AFTER_SECONDS,
} from './StreamStatsOverlay.constants';
import { TYPOGRAPHY } from '../../constants/typography';

/** Host load has no defensible threshold — we don't know the core count. Neutral by design. */
const loadTone = () => OVERLAY_COLORS.muted;

const percentTone = (value?: number): string => {
  if (typeof value !== 'number') return OVERLAY_COLORS.dim;
  if (value >= RESOURCE_ERROR_PERCENT) return OVERLAY_COLORS.error;
  if (value >= RESOURCE_WARN_PERCENT) return OVERLAY_COLORS.warn;
  return OVERLAY_COLORS.ok;
};

const levelTone = (value: number | null, warn: number, error: number): string => {
  if (value === null) return OVERLAY_COLORS.dim;
  if (value >= error) return OVERLAY_COLORS.error;
  if (value >= warn) return OVERLAY_COLORS.warn;
  return OVERLAY_COLORS.ok;
};

const formatAge = (seconds: number): string =>
  seconds < 60 ? `${Math.round(seconds)}s` : `${Math.floor(seconds / 60)}m`;

const Row: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <Box sx={{ display: 'flex', alignItems: 'baseline', mb: 0.25, whiteSpace: 'nowrap' }}>
    <Typography
      component="span"
      variant="body2"
      sx={{ color: OVERLAY_COLORS.text, mr: 1, fontFamily: 'inherit', fontSize: TYPOGRAPHY.caption.size }}
    >
      {label}:
    </Typography>
    <Typography
      component="span"
      variant="body2"
      sx={{ color: OVERLAY_COLORS.muted, fontFamily: 'inherit', fontSize: TYPOGRAPHY.caption.size }}
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
  /** WebRTC peer connection, when the picture is WebRTC: adds freeze / NACK / jitter readings. */
  pc?: RTCPeerConnection | null;
  /** The device on screen: picks its image telemetry out of the host stats. */
  deviceId?: string;
}

const formatBps = (bps: number | null): string => {
  if (bps === null) return '—';
  return bps >= 1_000_000 ? `${(bps / 1_000_000).toFixed(1)} Mbps` : `${Math.round(bps / 1000)} kbps`;
};
const formatMb = (bytes: number | null | undefined): string =>
  typeof bytes === 'number' ? `${Math.round(bytes / 1048576)} MB` : '—';

export const StreamStatsOverlay: React.FC<StreamStatsOverlayProps> = ({ host, live, pc = null, deviceId }) => {
  const rtc = useWebRTCStats(pc, pc !== null);
  const hasRtc = pc !== null && rtc.framesPerSecond !== null;
  // WebRTC has no buffered range to measure, so estimate: time held in the jitter buffer
  // plus half the round trip (host → browser). Encode and capture time are not counted.
  const rtcLatencySeconds =
    rtc.jitterBufferSeconds === null ? null : rtc.jitterBufferSeconds + (rtc.rttSeconds ?? 0) / 2;

  // One read on open, then only on the refresh button — no polling.
  const { snapshot, fetchedAt, loading, error, refresh } = useHostSnapshot(host);

  // Ticks the "checked Xs ago" label only; staleness is judged at fetch time below.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const stats = snapshot?.system_stats;
  const telemetry = deviceId ? stats?.image_telemetry?.[deviceId] : undefined;
  const services = useMemo(
    () => stats?.service_health?.services ?? [],
    [stats?.service_health?.services],
  );
  const watched = useMemo(
    () =>
      ['vpt-stream', 'vpt-monitor-img'].map(
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
  if (!hasLive && !hasHost && !hasRtc) return null;

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
        fontFamily: OVERLAY_FONT,
      }}
    >
      {hasRtc && (
        <>
          <Typography
            variant="body2"
            sx={{ color: OVERLAY_COLORS.text, fontFamily: 'inherit', fontSize: TYPOGRAPHY.caption.size, letterSpacing: 0.4, mb: 0.25 }}
          >
            STREAM · webrtc
          </Typography>
          <Row label="FPS">
            <Box component="span" sx={{ color: OVERLAY_COLORS.ok }}>
              {Math.round(rtc.framesPerSecond ?? 0)}
            </Box>
            {rtc.framesDropped ? (
              <Box component="span" sx={{ color: OVERLAY_COLORS.warn, ml: 1 }}>
                {rtc.framesDropped} dropped
              </Box>
            ) : null}
          </Row>
          {rtcLatencySeconds !== null && (
            <Row label="Latency">
              <Box component="span" sx={{ color: OVERLAY_COLORS.ok }}>
                ~{rtcLatencySeconds.toFixed(1)}s
              </Box>
            </Row>
          )}
          <Row label="Freeze">
            <Box
              component="span"
              sx={{ color: levelTone(rtc.freezePercent, FREEZE_WARN_PERCENT, FREEZE_ERROR_PERCENT) }}
            >
              {rtc.freezePercent === null ? '—' : `${rtc.freezePercent.toFixed(0)}%`}
            </Box>
            <Box component="span" sx={{ color: OVERLAY_COLORS.dim, ml: 1 }}>
              {rtc.freezeCount ?? 0} total
            </Box>
          </Row>
          <Row label="Network">
            <Box
              component="span"
              sx={{ color: levelTone(rtc.nackPercent, NACK_WARN_PERCENT, NACK_ERROR_PERCENT) }}
            >
              nack {rtc.nackPercent === null ? '—' : `${rtc.nackPercent.toFixed(1)}%`}
            </Box>
            {' · '}
            <Box
              component="span"
              sx={{
                color: levelTone(
                  rtc.jitterSeconds === null ? null : rtc.jitterSeconds * 1000,
                  JITTER_WARN_MS,
                  JITTER_ERROR_MS,
                ),
              }}
            >
              jit {rtc.jitterSeconds === null ? '—' : `${Math.round(rtc.jitterSeconds * 1000)}ms`}
            </Box>
            {rtc.rttSeconds !== null && ` · rtt ${Math.round(rtc.rttSeconds * 1000)}ms`}
          </Row>
          <Row label="Bitrate">
            {rtc.bitrateKbps === null ? '—' : `${Math.round(rtc.bitrateKbps)} kbps`}
            {rtc.packetsLost ? (
              <Box component="span" sx={{ color: OVERLAY_COLORS.error, ml: 1 }}>
                {rtc.packetsLost} lost
              </Box>
            ) : null}
          </Row>
          {hasHost && <Box sx={{ height: 6 }} />}
        </>
      )}
      {hasLive && (
        <>
          <Typography
            variant="body2"
            sx={{ color: OVERLAY_COLORS.text, fontFamily: 'inherit', fontSize: TYPOGRAPHY.caption.size, letterSpacing: 0.4, mb: 0.25 }}
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
                fontFamily: 'inherit',
                fontSize: TYPOGRAPHY.caption.size,
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
                <RefreshIcon sx={{ fontSize: TYPOGRAPHY.body.size }} />
              )}
            </IconButton>
          </Box>

          {heartbeatStale ? (
            <Typography
              variant="body2"
              sx={{ color: OVERLAY_COLORS.dim, fontFamily: 'inherit', fontSize: TYPOGRAPHY.caption.size }}
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
              <Row label="Disk">
                {/* disk_percent is the FULLEST monitored mount, not necessarily `/` — see
                    system_info_utils.get_disk_stats (BUG-0198). Show the mount in the
                    tooltip so the user can see whether the host's captures volume is
                    the one filling up. */}
                <Tooltip
                  arrow
                  placement="bottom"
                  title={
                    stats?.disk_worst_mount
                      ? `Worst mount: ${stats.disk_worst_mount}`
                      : 'Fullest monitored mount'
                  }
                >
                  <Box
                    component="span"
                    sx={{ color: percentTone(stats?.disk_percent), cursor: 'help' }}
                  >
                    {stats?.disk_percent !== undefined ? `${Math.round(stats.disk_percent)}%` : '—'}
                  </Box>
                </Tooltip>
                {((typeof stats?.disk_read_mb_per_sec === 'number' && stats.disk_read_mb_per_sec > 0) ||
                  (typeof stats?.disk_write_mb_per_sec === 'number' && stats.disk_write_mb_per_sec > 0)) && (
                  <>
                    {' · '}
                    <Box component="span" sx={{ color: OVERLAY_COLORS.muted }}>
                      R {((stats?.disk_read_mb_per_sec ?? 0)).toFixed(1)} MB/s
                    </Box>
                    <Box component="span" sx={{ color: OVERLAY_COLORS.muted }}>
                      {' · '}W {((stats?.disk_write_mb_per_sec ?? 0)).toFixed(1)} MB/s
                    </Box>
                  </>
                )}
              </Row>
              <Row label="Load">
                <Box component="span" sx={{ color: loadTone() }}>
                  {stats?.load_average_1m !== undefined ? stats.load_average_1m.toFixed(2) : '—'}
                </Box>
                {typeof telemetry?.process?.load_per_core === 'number' && (
                  <Box component="span" sx={{ color: OVERLAY_COLORS.dim }}>
                    {' · '}{telemetry.process.load_per_core.toFixed(2)}/core
                  </Box>
                )}
              </Row>
              {telemetry && (
                <>
                  {/* Image telemetry (TASK-157): what the monitor received over the last window, counted
                      before its drain. JPEG throughput, not the ffmpeg stream bitrate. */}
                  <Row label="Img in">
                    <Box component="span" sx={{ color: OVERLAY_COLORS.ok }}>
                      {telemetry.arrived_fps === null ? '—' : `${telemetry.arrived_fps.toFixed(1)} fps`}
                    </Box>
                    {' · '}
                    {formatBps(telemetry.estimated_image_throughput_bps)}
                  </Row>
                  <Row label="Img age">
                    <Box
                      component="span"
                      sx={{ color: levelTone(telemetry.frame_age_p95_ms, IMG_AGE_WARN_MS, IMG_AGE_ERROR_MS) }}
                    >
                      p95 {telemetry.frame_age_p95_ms === null ? '—' : `${Math.round(telemetry.frame_age_p95_ms)}ms`}
                    </Box>
                    {telemetry.frames_dropped > 0 && (
                      <Box component="span" sx={{ color: OVERLAY_COLORS.warn, ml: 1 }}>
                        {telemetry.frames_dropped} drop
                      </Box>
                    )}
                  </Row>
                  {telemetry.process && (
                    <Row label="Monitor">
                      {typeof telemetry.process.cpu_pct_monitor === 'number'
                        ? `${Math.round(telemetry.process.cpu_pct_monitor)}%`
                        : '—'}
                      {' · '}
                      {formatMb(telemetry.process.rss_monitor_bytes)}
                      {typeof telemetry.process.cpu_pct_ffmpeg === 'number' &&
                        ` · ffmpeg ${Math.round(telemetry.process.cpu_pct_ffmpeg)}%`}
                    </Row>
                  )}
                </>
              )}
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
                  sx={{ color: OVERLAY_COLORS.text, fontFamily: 'inherit', fontSize: TYPOGRAPHY.caption.size }}
                >
                  {unit}{' '}
                  <Box component="span" sx={{ color: look?.color ?? OVERLAY_COLORS.dim, fontFamily: 'inherit' }}>
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

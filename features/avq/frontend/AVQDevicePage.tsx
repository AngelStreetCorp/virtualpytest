import {
  ArrowBack as BackIcon,
  ExpandMore as ExpandMoreIcon,
  FiberManualRecord as LiveIcon,
  NavigateBefore as PrevIcon,
  NavigateNext as NextIcon,
  VolumeOff as MutedIcon,
  VolumeUp as UnmutedIcon,
} from '@mui/icons-material';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Grid,
  IconButton,
  Paper,
  Stack,
  Tab,
  Tabs,
  Tooltip,
  Typography,
} from '@mui/material';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { AVQFrameInspector } from './components/AVQFrameInspector';
import { AVQFrameStrip } from './components/AVQFrameStrip';
import { AVQTimeline } from './components/AVQTimeline';
import { EnhancedHLSPlayer } from '../../../frontend/src/components/video/EnhancedHLSPlayer';
import { buildStreamUrl } from '../../../frontend/src/utils/buildUrlUtils';
import { useAIContext } from '../../../frontend/src/contexts/AIContext';
import { useAVQMetrics, SUBTITLE_PRESENT, TRANSCRIPT_PRESENT } from './hooks/useAVQMetrics';
import { useAVQFrames } from './hooks/useAVQFrames';
import { useDeviceTimeline } from './hooks/useDeviceTimeline';
import { useMonitoring } from '../../../frontend/src/hooks/monitoring/useMonitoring';
import { useResponsiveMode } from '../../../frontend/src/hooks/useResponsiveMode';
import { formatScreenVerdict } from '../../../frontend/src/utils/screenVerdict';
import { useRec } from '../../../frontend/src/hooks/pages/useRec';

const mosColor = (v: number | null | undefined): string =>
  v == null ? '#9e9e9e' : v <= 0 ? '#f44336' : v >= 4 ? '#4caf50' : v >= 2.5 ? '#ff9800' : '#f44336';

const Stat: React.FC<{ label: string; value: React.ReactNode; color?: string }> = ({
  label,
  value,
  color,
}) => (
  <Box sx={{ minWidth: 72 }}>
    <Typography variant="caption" color="text.secondary" noWrap sx={{ fontSize: '0.68rem', lineHeight: 1 }}>
      {label}
    </Typography>
    <Typography variant="subtitle1" sx={{ color: color || 'text.primary', lineHeight: 1.2, fontWeight: 600 }}>
      {value}
    </Typography>
  </Box>
);

const AVQDevicePage: React.FC = () => {
  const { hostName, deviceId } = useParams<{ hostName: string; deviceId: string }>();
  const navigate = useNavigate();
  const { isMobile } = useResponsiveMode();
  const { avDevices } = useRec();
  const [muted, setMuted] = useState(true);
  const [isLiveMode, setIsLiveMode] = useState(true);
  const [archiveSeek, setArchiveSeek] = useState<{ time: number; nonce: number } | null>(null);
  const [selectedTime, setSelectedTime] = useState<number | null>(null);
  const [viewTab, setViewTab] = useState<'player' | 'frames'>('player');
  // Epoch of the still currently shown in the Frames inspector (reported up so the
  // tab-row controls can label the time and step from the right base).
  const [frameEpoch, setFrameEpoch] = useState<number | null>(null);
  const nonceRef = useRef(0);

  // Hide the global "Ask AI" floating button on this page (it overlaps the player).
  // Optional-chained so a stale/incomplete AIContext can never white-screen the page.
  const { pushFloatingButtonSuppress, popFloatingButtonSuppress } = useAIContext();
  useEffect(() => {
    pushFloatingButtonSuppress?.();
    return () => popFloatingButtonSuppress?.();
  }, [pushFloatingButtonSuppress, popFloatingButtonSuppress]);

  const match = useMemo(
    () =>
      avDevices.find(
        ({ host, device }) => host.host_name === hostName && device.device_id === deviceId,
      ),
    [avDevices, hostName, deviceId],
  );

  // VNC host devices ("host_vnc") have no HLS manifest at the live URL — their live view
  // is a noVNC iframe, which EnhancedHLSPlayer can't play (black screen). Their recorded
  // video lives at the capture/archive manifest, which for a VNC device resolves to the
  // live `segments/output.m3u8`. Pass that explicitly so the player shows real video.
  const streamUrlOverride = useMemo(() => {
    if (!match || match.device.device_model !== 'host_vnc') return undefined;
    try {
      return buildStreamUrl(match.host as any, deviceId, 'archive');
    } catch {
      return undefined;
    }
  }, [match, deviceId]);

  const { metrics, latest, isLoading, error } = useAVQMetrics(deviceId, hostName, 24);
  const { incidents, scripts, zaps } = useDeviceTimeline(
    hostName,
    deviceId,
    match?.device.device_name,
    24,
  );

  // The moment everything (right panel, timeline playhead, filmstrip) reflects:
  // on the Frames tab prefer the EXACT displayed-frame epoch the inspector reports
  // (one-way), else the user's selected time. On the Player tab use selectedTime.
  const displayTime = viewTab === 'frames' ? (frameEpoch ?? selectedTime) : selectedTime;

  // Screen-verdict sources (see the `screen` memo below):
  //  • Player → realtime per-frame Localize, the SAME feed the live overlay polls.
  //  • Frames → the SELECTED frame's stored verdict, looked up by epoch.
  const { latestAnalysis } = useMonitoring({
    host: match?.host,
    device: match?.device,
    enabled: viewTab === 'player' && !!match,
  });
  const framesTarget = viewTab === 'frames' ? frameEpoch ?? selectedTime : null;
  const { frameAt } = useAVQFrames(match?.host, deviceId, framesTarget);

  // When a moment is selected, show the metric sample nearest to it (instead of
  // "now"). Falls back to the latest sample in live mode.
  const selectedMetric = useMemo(() => {
    if (displayTime == null || metrics.length === 0) return null;
    let best = metrics[0];
    let bestD = Infinity;
    for (const m of metrics) {
      const d = Math.abs(new Date(m.timestamp).getTime() - displayTime);
      if (d < bestD) {
        bestD = d;
        best = m;
      }
    }
    return best;
  }, [displayTime, metrics]);
  const displayMetric = selectedMetric || latest;

  // SCREEN (Localize) — the SAME per-frame verdict the live overlay reads, formatted by
  // the SAME shared formatter (utils/screenVerdict). NOT derived from the per-minute RLE
  // spans (which lagged + drifted from the overlay). Player = realtime via useMonitoring;
  // Frames = the SELECTED frame's stored verdict via useAVQFrames. So all three surfaces
  // (overlay, AVQ Player, AVQ Frames) show the identical screen for the same instant.
  const screenVerdict =
    viewTab === 'frames'
      ? framesTarget != null
        ? frameAt(framesTarget)?.meta?.localize ?? null
        : null
      : latestAnalysis?.localize ?? null;
  const screen = formatScreenVerdict(screenVerdict);

  // Only treat transcript/subtitles as present when AVAILABILITY says so (>0.5,
  // same convention as the header chips) — a single false-positive OCR frame in a
  // minute leaves stray text in *_text with near-zero availability; don't show it.
  const hasTranscript =
    !!displayMetric && (displayMetric.transcript_available ?? 0) > TRANSCRIPT_PRESENT && !!displayMetric.transcript_text;
  const hasSubtitle =
    !!displayMetric && (displayMetric.subtitle_availability ?? 0) > SUBTITLE_PRESENT && !!displayMetric.subtitle_text;

  const fmt = (v: number | null | undefined, unit = '') =>
    v == null ? '—' : `${Math.round(v * 100) / 100}${unit}`;
  // Seconds + "(N×)" when the incident happened as more than one distinct event.
  const fmtIncident = (sec: number | null | undefined, key: string) => {
    const base = fmt(sec, 's');
    const n = displayMetric?.events?.[key]?.count;
    return n && n > 1 ? `${base} (${n}×)` : base;
  };
  const avail = (v: number | null | undefined) => (v == null ? '—' : v > 0.5 ? 'Yes' : 'No');
  const availColor = (v: number | null | undefined) =>
    v == null ? undefined : v > 0.5 ? '#4caf50' : '#f44336';

  const handleSeek = (epochMs: number) => {
    const d = new Date(epochMs);
    const tod = d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds();
    nonceRef.current += 1;
    setIsLiveMode(false);
    setArchiveSeek({ time: tod, nonce: nonceRef.current });
    setSelectedTime(epochMs);
  };
  const goLive = () => {
    setIsLiveMode(true);
    setArchiveSeek(null);
    setSelectedTime(null);
  };

  // Frames tab navigation (rendered on the tab row): step ±1s from the displayed
  // frame and pause live-follow; "go live" returns to following the newest still.
  const framesLive = selectedTime == null;
  const stepFrame = (deltaMs: number) => {
    const base = frameEpoch ?? selectedTime ?? Date.now() - 35_000;
    setSelectedTime(base + deltaMs);
  };
  const framesGoLive = () => setSelectedTime(null);
  useEffect(() => {
    if (viewTab !== 'frames') return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault(); // don't let arrow keys scroll the page
      const base = frameEpoch ?? selectedTime ?? Date.now() - 35_000;
      setSelectedTime(base + (e.key === 'ArrowLeft' ? -1000 : 1000));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [viewTab, frameEpoch, selectedTime]);

  return (
    <Box sx={{ px: 2, pt: 0, pb: 1 }}>
      {/* Header */}
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <Tooltip title="Back to devices">
          <IconButton size="small" onClick={() => navigate('/device-control')}>
            <BackIcon />
          </IconButton>
        </Tooltip>
        <Typography variant="h6">
          {match?.device.device_name || deviceId} · {hostName}
        </Typography>
        <Box sx={{ flex: 1 }} />
        {displayMetric && (
          <>
            <Chip size="small" label={`Video ${avail(displayMetric.video_availability)}`} sx={{ bgcolor: availColor(displayMetric.video_availability) || '#9e9e9e', color: '#fff' }} />
            <Chip size="small" label={`Video MOS ${fmt(displayMetric.video_mos)}`} sx={{ bgcolor: mosColor(displayMetric.video_mos), color: '#fff' }} />
            {!isMobile && (
              <>
                <Chip size="small" label={`Audio ${avail(displayMetric.audio_availability)}`} sx={{ bgcolor: availColor(displayMetric.audio_availability) || '#9e9e9e', color: '#fff' }} />
                <Chip size="small" label={`Audio MOS ${fmt(displayMetric.audio_mos)}`} sx={{ bgcolor: mosColor(displayMetric.audio_mos), color: '#fff' }} />
              </>
            )}
          </>
        )}
      </Stack>

      <Grid container spacing={1.5}>
        {/* Stream / Frames (top-left) */}
        <Grid item xs={12} md={6}>
          <Paper variant="outlined" sx={{ p: 1, height: 336, display: 'flex', flexDirection: 'column' }}>
            {/* one title line: tabs (left) + per-tab controls (right) */}
            <Stack direction="row" alignItems="center" spacing={0.5} sx={{ mb: 0.5 }}>
              <Tabs
                value={viewTab}
                onChange={(_, v) => setViewTab(v)}
                sx={{ minHeight: 0, '& .MuiTab-root': { minHeight: 0, py: 0.5 } }}
              >
                <Tab value="player" label="Player" />
                <Tab value="frames" label="Frames" />
              </Tabs>
              <Box sx={{ flex: 1 }} />
              {viewTab === 'player' ? (
                <>
                  {isLiveMode ? (
                    <Typography variant="body2" sx={{ color: '#f44336', fontWeight: 700, display: 'flex', alignItems: 'center' }}>
                      <LiveIcon sx={{ fontSize: 11, mr: 0.5 }} /> LIVE
                    </Typography>
                  ) : (
                    <>
                      <Button size="small" variant="outlined" onClick={goLive} startIcon={<LiveIcon sx={{ fontSize: 11 }} />}>
                        Back to live
                      </Button>
                      <Typography variant="caption" color="text.secondary">
                        {selectedTime ? new Date(selectedTime).toLocaleTimeString() : ''}
                      </Typography>
                    </>
                  )}
                  <IconButton size="small" onClick={() => setMuted((m) => !m)}>
                    {muted ? <MutedIcon fontSize="small" /> : <UnmutedIcon fontSize="small" />}
                  </IconButton>
                </>
              ) : (
                <>
                  <Typography variant="caption" color="text.secondary">
                    {frameEpoch != null
                      ? new Date(frameEpoch).toLocaleTimeString([], { hour12: false })
                      : '—'}
                  </Typography>
                  <Tooltip title="Jump to latest frame">
                    <IconButton size="small" onClick={framesGoLive}>
                      <LiveIcon sx={{ fontSize: 14, color: framesLive ? '#888' : '#f44336' }} />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title="Previous frame (←)">
                    <IconButton size="small" onClick={() => stepFrame(-1000)}>
                      <PrevIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title="Next frame (→)">
                    <IconButton size="small" onClick={() => stepFrame(1000)}>
                      <NextIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </>
              )}
            </Stack>

            {viewTab === 'player' ? (
              <Box sx={{ position: 'relative', width: '100%', flex: 1, minHeight: 230, bgcolor: 'black', overflow: 'hidden', borderRadius: 1 }}>
                {match ? (
                  <EnhancedHLSPlayer
                    deviceId={deviceId || 'device1'}
                    hostName={hostName || ''}
                    host={match.host as any}
                    streamUrl={streamUrlOverride}
                    isLiveMode={isLiveMode}
                    archiveSeek={archiveSeek}
                    freezeArchiveFrame={!isLiveMode}
                    hideTimelineOverlay
                    muted={muted}
                    width="100%"
                    height="100%"
                  />
                ) : (
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
                    <CircularProgress size={20} />
                  </Box>
                )}
              </Box>
            ) : match ? (
              <AVQFrameInspector
                host={match.host as any}
                deviceId={deviceId || 'device1'}
                selectedTime={selectedTime}
                onFrameTime={setFrameEpoch}
              />
            ) : (
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1 }}>
                <CircularProgress size={20} />
              </Box>
            )}
          </Paper>
        </Grid>

        {/* NOW panel (top-right) */}
        <Grid item xs={12} md={6}>
          <Paper variant="outlined" sx={{ p: 1.5, height: 336, overflowY: "auto" }}>
            <Typography
              variant="subtitle2"
              component="div"
              sx={{ display: 'flex', alignItems: 'baseline', gap: 0.75, flexWrap: 'wrap' }}
            >
              <span>
                {displayTime != null
                  ? `Selected · ${new Date(displayTime).toLocaleTimeString()}`
                  : 'Now (last minute)'}
              </span>
              <Box component="span" sx={{ color: screen.color, fontWeight: 600 }}>
                · {screen.text}
              </Box>
            </Typography>
            <Divider sx={{ my: 1 }} />
            {!displayMetric && isLoading && <CircularProgress size={18} />}
            {!displayMetric && !isLoading && (
              <Typography color="text.secondary" variant="body2">
                No AVQ data yet. (Is vpt-avq.service running on the host?)
              </Typography>
            )}
            {error && (
              <Typography color="error" variant="body2">
                {error}
              </Typography>
            )}
            {displayMetric && (
              <>
                <Typography variant="overline" color="text.secondary">Video</Typography>
                <Stack direction="row" flexWrap="wrap" gap={1.25} sx={{ mb: 0.75 }}>
                  <Stat label="Available" value={avail(displayMetric.video_availability)} color={availColor(displayMetric.video_availability)} />
                  <Stat label="Video MOS" value={fmt(displayMetric.video_mos)} color={mosColor(displayMetric.video_mos)} />
                  <Stat label="Bluriness" value={fmt(displayMetric.blurriness_score)} />
                  <Stat label="Blockiness" value={fmt(displayMetric.blockiness_score)} />
                  <Stat label="Jerkiness" value={fmt(displayMetric.jerkiness_score)} />
                  <Stat label="Blackscreen" value={fmtIncident(displayMetric.blackscreen_seconds, 'blackscreen')} />
                  <Stat label="Freeze" value={fmtIncident(displayMetric.freeze_seconds, 'freeze')} />
                  <Stat label="Macroblocks" value={fmtIncident(displayMetric.macroblocks_seconds, 'macroblocks')} />
                </Stack>
                {!isMobile && (
                  <>
                    <Divider sx={{ my: 0.75 }} />
                    <Typography variant="overline" color="text.secondary">Audio</Typography>
                    <Stack direction="row" flexWrap="wrap" gap={1.25}>
                      <Stat label="Available" value={avail(displayMetric.audio_availability)} color={availColor(displayMetric.audio_availability)} />
                      <Stat label="Audio MOS" value={fmt(displayMetric.audio_mos)} color={mosColor(displayMetric.audio_mos)} />
                      <Stat label="Audio Level" value={fmt(displayMetric.audio_level_db, ' dB')} />
                      <Stat label="Loudness" value={fmt(displayMetric.loudness_lkfs, ' LKFS')} />
                      <Stat label="Silence" value={fmtIncident(displayMetric.silence_seconds, 'noSound')} />
                      <Stat label="Saturation" value={fmt(displayMetric.saturation_score)} />
                    </Stack>
                  </>
                )}
              </>
            )}
          </Paper>
        </Grid>

        {/* 24h timeline (full width) — collapsible; click to seek */}
        <Grid item xs={12}>
          <Accordion variant="outlined" disableGutters defaultExpanded>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle2">
                Last 24h ({metrics.length} samples · {incidents.length} incidents · {scripts.length} runs · {zaps.length} zaps) — click to seek
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <AVQTimeline
                metrics={metrics}
                incidents={incidents}
                scripts={scripts}
                zaps={zaps}
                hours={24}
                onSeek={handleSeek}
                selectedTime={displayTime}
              />
            </AccordionDetails>
          </Accordion>
        </Grid>

        {/* Audio Transcript + Subtitles — collapsible; text shown only when actually present. */}
        <Grid item xs={12}>
          <Accordion variant="outlined" disableGutters defaultExpanded={false}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="body2">
                <Box component="span" sx={{ fontWeight: 600 }}>Audio Transcript: </Box>
                {hasTranscript
                  ? `Yes${displayMetric?.transcript_language ? ` (${displayMetric.transcript_language})` : ''}`
                  : 'No'}
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Typography variant="body2" sx={{ color: 'text.secondary', whiteSpace: 'pre-wrap' }}>
                {hasTranscript ? displayMetric?.transcript_text : 'No transcription for this time.'}
              </Typography>
            </AccordionDetails>
          </Accordion>
          <Accordion variant="outlined" disableGutters defaultExpanded={false} sx={{ mt: 1 }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="body2">
                <Box component="span" sx={{ fontWeight: 600 }}>Subtitles: </Box>
                {hasSubtitle
                  ? `Yes${displayMetric?.subtitle_language ? ` (${displayMetric.subtitle_language})` : ''}`
                  : 'No'}
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Typography variant="body2" sx={{ color: 'text.secondary', whiteSpace: 'pre-wrap' }}>
                {hasSubtitle ? displayMetric?.subtitle_text : 'No subtitles for this time.'}
              </Typography>
            </AccordionDetails>
          </Accordion>
        </Grid>

        {/* Details — ±5 context filmstrip; only on the Frames tab (showing stills next to the
            Player's preview video is confusing). */}
        {viewTab === 'frames' && (
        <Grid item xs={12}>
          <Accordion variant="outlined" disableGutters defaultExpanded={false} TransitionProps={{ unmountOnExit: true }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle2">
                Details — frames around{' '}
                {displayTime != null
                  ? new Date(displayTime).toLocaleTimeString([], { hour12: false })
                  : '—'}{' '}
                (1 fps)
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              {match ? (
                <AVQFrameStrip
                  host={match.host as any}
                  deviceId={deviceId || 'device1'}
                  centerEpoch={displayTime}
                  selectedEpoch={displayTime}
                  onSelect={(epochMs) => {
                    setIsLiveMode(false);
                    setSelectedTime(epochMs);
                  }}
                />
              ) : (
                <CircularProgress size={18} />
              )}
            </AccordionDetails>
          </Accordion>
        </Grid>
        )}
      </Grid>
    </Box>
  );
};

export default AVQDevicePage;

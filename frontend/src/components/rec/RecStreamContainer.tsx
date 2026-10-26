import { Box, Typography, CircularProgress } from '@mui/material';
import React, { useMemo, useRef, useState, useLayoutEffect, useEffect, useCallback } from 'react';

import { Host, Device } from '../../types/common/Host_Types';
import { MonitoringAnalysis, SubtitleAnalysis, LanguageMenuAnalysis } from '../../types/pages/Monitoring_Types';
import { EnhancedHLSPlayer } from '../video/EnhancedHLSPlayer';
import { HLSVideoPlayer } from '../common/HLSVideoPlayer';
import { LiveStreamSwitch } from '../common/LiveStream/LiveStreamSwitch';
import type { LiveStreamTransport, WhepStatus } from '../../types/controller/WebRTC_Types';
import { AnalysedFrameLayer } from '../monitoring/AnalysedFrameLayer';
import { MonitoringOverlay } from '../monitoring/MonitoringOverlay';
import { DroneTelemetryOverlay } from './DroneBatteryBadge';
import { LocalizeVideoBadge } from './LocalizeVideoBadge';
import { StreamStatsOverlay } from '../monitoring/StreamStatsOverlay';
import { useWebRTCStats } from '../../hooks/controller/useWebRTCStats';
import { useLiveStreamStats, type LiveStreamStats } from '../video/hooks/useLiveStreamStats';
import { buildCaptureUrl, buildMetadataFileUrl, buildStreamUrl, withVncCacheBust } from '../../utils/buildUrlUtils';
import { withVncViewportScale } from '../../utils/vncUtils';
import { useHostSession } from '../../hooks/useHostSession';
import { useVncPassword } from '../../hooks/controller/useVncPassword';
import { RestartPlayer } from './RestartPlayer';

interface ErrorTrendData {
  blackscreenConsecutive: number;
  freezeConsecutive: number;
  audioLossConsecutive: number;
  macroblocksConsecutive: number;
  hasWarning: boolean;
  hasError: boolean;
}

interface RecStreamContainerProps {
  host: Host;
  device?: Device;
  
  // Stream state
  streamUrl?: string;
  isLoadingUrl: boolean;
  urlError: string | null;
  
  // Mode states
  monitoringMode: boolean;
  restartMode: boolean;
  isLiveMode: boolean;
  
  // Control state
  isControlActive: boolean;
  
  // Quality state
  currentQuality: 'low' | 'sd' | 'hd' | 'hd_plus';
  isQualitySwitching: boolean;
  shouldPausePlayer: boolean;

  // Live transport (HLS / WebRTC toggle)
  streamTransport: LiveStreamTransport;
  onWebRTCFailed: (reason: string) => void;
  
  // Audio state
  isMuted: boolean;
  
  // Layout
  isMobileModel: boolean;
  showRemote: boolean;
  showWeb: boolean;
  finalStreamContainerDimensions: {
    width: number;
    height: number;
    x: number;
    y: number;
  };
  
  // VNC scaling function
  
  // Callbacks
  onPlayerReady: () => void;
  onVideoTimeUpdate: (time: number) => void;
  onVideoPause?: () => void;
  onCurrentSegmentChange?: (segmentUrl: string) => void;

  // Archive mode: open at this time (archive global seconds = host time of day) once the manifest is loaded
  archiveSeek?: { time: number; nonce: number } | null;
  
  // Monitoring data props (for overlay on live video)
  monitoringAnalysis?: MonitoringAnalysis;
  subtitleAnalysis?: SubtitleAnalysis;
  languageMenuAnalysis?: LanguageMenuAnalysis;
  aiDescription?: string;
  errorTrendData?: ErrorTrendData;
  analysisTimestamp?: string;
  isAIAnalyzing?: boolean;
  /** Live capture FPS from the monitor (sequence deltas). */
  captureFps?: number | null;

  // Reports the real rendered stream box (page coordinates) as it's measured, so callers
  // that position overlays on top of the video (e.g. the Android mobile tap/element
  // overlay) can use the actual box instead of the pre-render size estimate.
  onMeasuredAreaChange?: (rect: { width: number; height: number; x: number; y: number }) => void;

  /**
   * When true, the HLS player's latency-debug overlay is on (in addition to the
   * `?latency_debug=1` URL trigger). Wired through to HLSVideoPlayer so the
   * rec header can show its own "Latency" toggle without the user editing the URL.
   */
  latencyDebug?: boolean;
  persistentStream?: boolean;
  onPersistentStreamTargetChange?: (target: HTMLElement | null) => void;
  persistentWebRtcStatus?: WhepStatus;
}

export const RecStreamContainer: React.FC<RecStreamContainerProps> = ({
  host,
  device,
  streamUrl,
  isLoadingUrl,
  urlError,
  monitoringMode,
  restartMode,
  isLiveMode,
  isControlActive,
  currentQuality,
  isQualitySwitching,
  shouldPausePlayer,
  streamTransport,
  onWebRTCFailed,
  isMuted,
  isMobileModel,
  showRemote,
  showWeb,
  finalStreamContainerDimensions,
  onPlayerReady,
  onVideoTimeUpdate,
  onVideoPause,
  onCurrentSegmentChange,
  archiveSeek,
  // Monitoring props
  monitoringAnalysis,
  subtitleAnalysis,
  languageMenuAnalysis,
  aiDescription,
  errorTrendData,
  analysisTimestamp,
  isAIAnalyzing,
  captureFps = null,
  onMeasuredAreaChange,
  latencyDebug,
  persistentStream = false,
  onPersistentStreamTargetChange,
  persistentWebRtcStatus,
}) => {
  // Latest WHEP status reported up from LiveStreamSwitch. We track it locally so we can
  // show the content-area loading overlay while WebRTC is connecting (mirrors the
  // LOW/SD/HD quality-switch overlay — keeps the WEB toggle button clean).
  const [whepStatus, setWhepStatus] = useState<WhepStatus>('idle');
  // Surface the overlay only while the operator is in WEB mode AND the WHEP session is
  // still handshaking. After 'playing' the WebRTC <video> takes over; on 'failed' the
  // parent flips transport back to HLS and this branch becomes unreachable.
  const isWebRtcConnecting =
    streamTransport === 'webrtc' && isLiveMode && (persistentWebRtcStatus ?? whepStatus) === 'connecting';

  // VNC archive mode: override streamUrl to use HLS (same as screenshot logic)
  const isVncDevice = device?.device_model === 'host_vnc';
  const audioSupported = !isVncDevice;

  const persistentSlotRef = useRef<HTMLDivElement | null>(null);
  const persistentVideoRef = useRef<HTMLVideoElement | null>(null);
  useEffect(() => {
    if (!persistentStream || !monitoringMode) {
      persistentVideoRef.current = null;
      return undefined;
    }
    const bind = () => {
      persistentVideoRef.current = persistentSlotRef.current?.querySelector('video') ?? null;
    };
    bind();
    const id = window.setInterval(bind, 1000);
    return () => {
      window.clearInterval(id);
      persistentVideoRef.current = null;
    };
  }, [persistentStream, monitoringMode]);
  const persistentLive = useLiveStreamStats(
    persistentVideoRef,
    Boolean(persistentStream && monitoringMode && isLiveMode),
    isLiveMode,
  );

  const handlePersistentSlotRef = useCallback(
    (el: HTMLDivElement | null) => {
      persistentSlotRef.current = el;
      onPersistentStreamTargetChange?.(el);
    },
    [onPersistentStreamTargetChange],
  );

  // Monitoring cards + host stats over a player that has no built-in overlay: the VNC
  // iframe and the WebRTC <video> (EnhancedHLSPlayer draws its own). The VNC iframe has no
  // live row; the WebRTC <video> passes its peer connection so the overlay can read getStats().
  const renderMonitoringLayer = (pc?: RTCPeerConnection | null, live?: LiveStreamStats | null) =>
    monitoringMode ? (
    <RecMonitoringLayer
      host={host}
      device={device}
      pc={pc}
      monitoringAnalysis={monitoringAnalysis}
      subtitleAnalysis={subtitleAnalysis}
      languageMenuAnalysis={languageMenuAnalysis}
      errorTrendData={errorTrendData}
      analysisTimestamp={analysisTimestamp}
      isAIAnalyzing={isAIAnalyzing}
      audioSupported={audioSupported}
      captureFps={captureFps}
      playbackFps={live?.fps ?? null}
      live={live}
    />
  ) : null;
  const monitoringLayer = renderMonitoringLayer(null, persistentStream ? persistentLive : null);
  const archiveStreamBuild = useMemo(() => {
    if (!isVncDevice || isLiveMode) {
      return { url: undefined as string | undefined, error: null as string | null };
    }
    // Guard: skip if device has no video_capture_path — avoids spurious console errors
    const deviceId = device?.device_id || 'device1';
    const deviceConfig = host?.devices?.find((d: any) => d?.device_id === deviceId);
    if (!deviceConfig?.video_capture_path) {
      return { url: undefined, error: null };
    }
    try {
      const url = buildStreamUrl(host, deviceId, 'archive');
      return { url, error: null };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to resolve archive stream URL';
      console.error('[RecStreamContainer] Archive stream URL build failed', {
        hostName: host?.host_name,
        deviceId,
        message,
      });
      return { url: undefined, error: message };
    }
  }, [isVncDevice, isLiveMode, host, device?.device_id]);

  // VNC live audio workaround: the noVNC iframe carries no audio (RFB has no audio
  // channel), but the HLS capture stream now muxes the desktop's PulseAudio. In live
  // mode we mount a hidden HLSVideoPlayer on this URL purely for its audio track, synced
  // to the existing mute toggle. For a VNC device, mode 'archive' resolves to the live
  // manifest (.../segments/output.m3u8), which is exactly the stream we want.
  const vncLiveAudioUrl = useMemo(() => {
    if (!isVncDevice || !isLiveMode) return undefined;
    const deviceId = device?.device_id || 'device1';
    const deviceConfig = host?.devices?.find((d: any) => d?.device_id === deviceId);
    if (!deviceConfig?.video_capture_path) return undefined;
    try {
      return buildStreamUrl(host, deviceId, 'archive');
    } catch {
      return undefined;
    }
  }, [isVncDevice, isLiveMode, host, device?.device_id]);

  const effectiveStreamUrl = (isVncDevice && !isLiveMode)
    ? archiveStreamBuild.url
    : streamUrl;
  const effectiveUrlError = archiveStreamBuild.error || urlError;

  // Only a host with HOST_VNC_AUTOCONNECT=true returns a password; others stay URL-clean.
  const { vncPasswordReady, withVncPassword } = useVncPassword(isVncDevice && isLiveMode ? host : null);

  // BUG-0107 step 2: the proxy's auth_request gate rejects the iframe's navigation to
  // /host/<name>/vnc_lite.html without this cookie. Must be set BEFORE the iframe is
  // given a src, so the live VNC iframe only renders once the mint call resolves. Not
  // keepAlive: the websocket handshake is the only request the gate ever sees, the
  // connection then persists independent of cookie expiry (unlike the HLS companion
  // player below, which is gated internally by HLSVideoPlayer itself).
  const isLiveVnc = isVncDevice && isLiveMode && !!effectiveStreamUrl;
  const vncSessionReady = useHostSession(isLiveVnc ? effectiveStreamUrl : null, false);
  // Measure the stream area for overlays and the archive player. The live VNC
  // iframe fills this box; noVNC scales the server's actual framebuffer inside it.
  const streamAreaRef = useRef<HTMLDivElement | null>(null);
  const [measuredStreamArea, setMeasuredStreamArea] = useState<{ width: number; height: number } | null>(null);
  useLayoutEffect(() => {
    const el = streamAreaRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const update = () => {
      const { width, height, left, top } = el.getBoundingClientRect();
      setMeasuredStreamArea((prev) =>
        prev && prev.width === width && prev.height === height ? prev : { width, height },
      );
      // Report the real box (not the pre-render estimate) so overlays positioned on top
      // of the video — e.g. the Android mobile tap/element overlay — line up with it in
      // every orientation instead of a formula-based guess that ignores landscape.
      onMeasuredAreaChange?.({ width, height, x: left, y: top });
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [onMeasuredAreaChange]);
  // The measured height is the box the video actually gets. finalStreamContainerDimensions
  // caps its height to the LANDSCAPE default resolution, which on a narrow (mobile) viewport
  // collapses the player to ~width*0.56 and shrinks the video right after the poster fades.
  const streamAreaHeight = measuredStreamArea?.height || finalStreamContainerDimensions.height;

  return (
    <Box
      ref={streamAreaRef}
      sx={{
        width: (() => {
          if (!isControlActive) return '100%';
          const panelCount = (showRemote ? 1 : 0) + (showWeb ? 1 : 0);
          if (panelCount === 0) return '100%';
          if (panelCount === 1) return '80%'; // Changed from 75% to 80% (100% - 20%)
          return '60%'; // Changed from 50% to 60% (100% - 40% for two 20% panels)
        })(),
        height: '100%', // Use full available height (already excluding header)
        position: 'relative',
        overflow: 'hidden',
        display: 'flex',
        alignItems: isMobileModel ? 'flex-start' : 'center', // Top-align mobile to avoid bottom black bars
        justifyContent: 'center',
        backgroundColor: 'black',
      }}
    >
      {/* Drone battery, temperature, speed and height, top-right on the video */}
      {/* (the monitoring layer's drone HUD replaces it while the drone profile's frames are shown) */}
      {!(monitoringMode && monitoringAnalysis?.ui?.hud) && <DroneTelemetryOverlay host={host} device={device} full />}
      {/* Monitor's Localize verdict (tv_app profile, TASK-115). Stays up in monitoring
          mode too: the overlay's Screen line is top-left; this chip is top-right. */}
      <LocalizeVideoBadge host={host} device={device} full />

      {/* Stream transition overlay - solid black to hide corrupted/blank frames during
          a quality switch OR a WebRTC hand-off. The toolbar stays clean: the LOW/SD/HD
          and WEB toggle buttons don't carry inline spinners, the loading lives here. */}
      {(isQualitySwitching || isWebRtcConnecting) && (
          <Box
            sx={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: 'black', // Solid black to completely hide any corruption
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 1000,
            }}
          >
            <CircularProgress size={60} sx={{ color: 'warning.main' }} />
            <Typography variant="h6" sx={{ color: 'white', mt: 2 }}>
              {isQualitySwitching
                ? `Loading ${currentQuality.toUpperCase()} quality stream...`
                : 'Loading WebRTC stream...'}
            </Typography>
            <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.7)', mt: 1 }}>
              Waiting for stable stream
            </Typography>
          </Box>
        )}
      
      {/* Content based on mode */}
      {persistentStream ? (
        <Box
          ref={handlePersistentSlotRef}
          data-persistent-stream-slot
          sx={{ position: 'absolute', inset: 0, backgroundColor: 'black' }}
        >
          {monitoringLayer}
        </Box>
      ) : restartMode && isControlActive ? (
        <RestartPlayer host={host} device={device!} includeAudioAnalysis={true} />
      ) : effectiveStreamUrl ? (
        // VNC device in LIVE mode: use iframe for live desktop stream
        // VNC device in ARCHIVE mode: use HLS player for recorded video
        // Non-VNC devices: always use HLS player
        device?.device_model === 'host_vnc' && isLiveMode ? (
          <Box
            sx={{
              position: 'relative',
              width: '100%',
              height: '100%',
              backgroundColor: 'black',
              overflow: 'hidden',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {vncSessionReady && vncPasswordReady && (
            <iframe
              src={withVncViewportScale(withVncCacheBust(withVncPassword(effectiveStreamUrl)))}
              style={{
                border: 'none',
                backgroundColor: '#000',
                display: 'block',
                pointerEvents: isControlActive ? 'auto' : 'none',
                width: '100%',
                height: '100%',
                flexShrink: 0,
              }}
              title="VNC Desktop Stream"
              allow="fullscreen"
            />
            )}

            {/* Hidden HLS companion: provides audio for the VNC desktop (noVNC has no
                audio channel). Plays muted by default; the header mute toggle unmutes it.
                Audio trails the live VNC video by ~one HLS segment (~4-6s). */}
            {vncLiveAudioUrl && (
              <Box
                sx={{
                  position: 'absolute',
                  width: '1px',
                  height: '1px',
                  opacity: 0,
                  pointerEvents: 'none',
                  overflow: 'hidden',
                  bottom: 0,
                  left: 0,
                }}
                aria-hidden
              >
                <HLSVideoPlayer
                  streamUrl={vncLiveAudioUrl}
                  isStreamActive={true}
                  muted={isMuted}
                  isArchiveMode={false}
                  latencyDebug={latencyDebug}
                  sx={{ width: '1px', height: '1px' }}
                />
              </Box>
            )}
            
            {/* Monitoring overlay for VNC - same as HLS */}
            {monitoringLayer}
          </Box>
        ) : (
          // Live + RTC toggle on: WebRTC replaces the HLS player once it shows a frame,
          // with the same monitoring layer on top (the transcript rail stays HLS-only).
          // Archive is always HLS.
          <LiveStreamSwitch
            streamUrl={effectiveStreamUrl}
            webrtcEnabled={isLiveMode && streamTransport === 'webrtc'}
            muted={isMuted}
            webrtcOverlay={renderMonitoringLayer}
            reconnectKey={currentQuality}
            onStatusChange={setWhepStatus}
            onWebRTCFailed={onWebRTCFailed}
            sx={{ height: streamAreaHeight }}
          >
          <EnhancedHLSPlayer
            deviceId={device?.device_id || 'device1'}
            hostName={host.host_name}
            host={host}
            streamUrl={effectiveStreamUrl}
            width="100%"
            height={streamAreaHeight}
            muted={isMuted}
            isLiveMode={isLiveMode}
            archiveSeek={archiveSeek}
            quality={currentQuality}
            shouldPause={shouldPausePlayer}
            onPlayerReady={onPlayerReady}
            onVideoTimeUpdate={onVideoTimeUpdate}
            onVideoPause={onVideoPause}
            onCurrentSegmentChange={onCurrentSegmentChange}
            // Live transcript rail (TASK-05). Needs ENABLE_TRANSCRIPTION=true on the
            // host; VNC devices have no audio and are skipped inside the hook.
            showLiveTranscriptRail={audioSupported}
            // Monitoring overlay props
            monitoringMode={monitoringMode}
            monitoringAnalysis={monitoringAnalysis}
            subtitleAnalysis={subtitleAnalysis}
            languageMenuAnalysis={languageMenuAnalysis}
            aiDescription={aiDescription}
            errorTrendData={errorTrendData}
            analysisTimestamp={analysisTimestamp}
            isAIAnalyzing={isAIAnalyzing}
            captureFps={captureFps}
          />
          </LiveStreamSwitch>
        )
      ) : (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            color: 'white',
          }}
        >
          <Typography>
              {isLoadingUrl
                ? 'Loading stream...'
                : effectiveUrlError
                  ? 'Stream error'
                  : 'No stream available'}
          </Typography>
        </Box>
      )}
    </Box>
  );
};

/** Monitoring cards + host stats. A component so WebRTC `pc` can feed FPS out via getStats(). */
const RecMonitoringLayer: React.FC<{
  host: Host;
  device?: Device;
  pc?: RTCPeerConnection | null;
  monitoringAnalysis?: MonitoringAnalysis;
  subtitleAnalysis?: SubtitleAnalysis;
  languageMenuAnalysis?: LanguageMenuAnalysis;
  errorTrendData?: ErrorTrendData;
  analysisTimestamp?: string;
  isAIAnalyzing?: boolean;
  audioSupported: boolean;
  captureFps?: number | null;
  playbackFps?: number | null;
  live?: LiveStreamStats | null;
}> = ({
  host,
  device,
  pc = null,
  monitoringAnalysis,
  subtitleAnalysis,
  languageMenuAnalysis,
  errorTrendData,
  analysisTimestamp,
  isAIAnalyzing,
  audioSupported,
  captureFps = null,
  playbackFps = null,
  live = null,
}) => {
  const rtc = useWebRTCStats(pc, pc !== null);
  const fpsOut =
    playbackFps != null
      ? playbackFps
      : pc !== null && rtc.framesPerSecond !== null
        ? Math.round(rtc.framesPerSecond)
        : null;
  // BUG-0836: when a profile overlay is drawing, show the exact capture its boxes were measured on.
  // The boxes and the picture are then the same frame, so they cannot drift apart no matter what the scene
  // does; the live stream stays one click away for watching the device itself.
  const frameLocked = true; // the analysed frame is the picture under a profile overlay (BUG-0836)
  const overlayProfile = monitoringAnalysis?.profile;
  const overlayActive = !!overlayProfile && overlayProfile !== 'tv_app' && !monitoringAnalysis?.ui?.hud;
  const sequence = monitoringAnalysis?.filename?.match(/capture_(\d+)/)?.[1] ?? null;
  const analysedFrameUrl = useMemo(() => {
    if (!sequence || !device?.device_id) return null;
    try {
      return buildCaptureUrl(host, sequence, device.device_id);
    } catch {
      return null;
    }
  }, [host, sequence, device?.device_id]);

  const profileName = device?.device_id
    ? host.system_stats?.monitor_profiles?.[device.device_id]
    : undefined;
  // BUG-0575: ffmpeg-configured input rate, parsed on the host from the live
  // ffmpeg process cmdline (`-framerate N`). Shown as the "in" value of the
  // overlay's FPS line so the operator can tell "what ffmpeg was told" from
  // "what we actually measure" (captureFps below, from sequence deltas).
  const fpsInConfigured = device?.device_id
    ? host.system_stats?.stream_capture_fps?.[device.device_id] ?? null
    : null;

  return (
    <Box
      sx={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        pointerEvents: 'none',
        zIndex: 1300,
      }}
    >
      <AnalysedFrameLayer
        url={analysedFrameUrl}
        active={overlayActive}
        frameLocked={frameLocked}
      />
      <MonitoringOverlay
        frameLocked={frameLocked && overlayActive}
        frameUrl={analysedFrameUrl}
        metadataUrl={device?.device_id ? (fileName: string) => buildMetadataFileUrl(host, device.device_id, fileName) : undefined}
        monitoringAnalysis={monitoringAnalysis || undefined}
        subtitleAnalysis={subtitleAnalysis}
        languageMenuAnalysis={languageMenuAnalysis}
        consecutiveErrorCounts={errorTrendData || undefined}
        audioSupported={audioSupported}
        showSubtitles={!!subtitleAnalysis}
        showLanguageMenu={!!languageMenuAnalysis}
        analysisTimestamp={analysisTimestamp || undefined}
        isAIAnalyzing={isAIAnalyzing}
        profileName={profileName}
        fpsIn={captureFps}
        fpsInConfigured={fpsInConfigured}
        fpsOut={fpsOut}
      />
      <StreamStatsOverlay host={host} pc={pc} live={live} deviceId={device?.device_id} />
    </Box>
  );
};

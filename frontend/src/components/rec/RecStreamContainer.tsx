import { Box, Typography, CircularProgress } from '@mui/material';
import React, { useMemo, useRef, useState, useLayoutEffect } from 'react';

import { Host, Device } from '../../types/common/Host_Types';
import { MonitoringAnalysis, SubtitleAnalysis, LanguageMenuAnalysis } from '../../types/pages/Monitoring_Types';
import { EnhancedHLSPlayer } from '../video/EnhancedHLSPlayer';
import { HLSVideoPlayer } from '../common/HLSVideoPlayer';
import { MonitoringOverlay } from '../monitoring/MonitoringOverlay';
import { buildStreamUrl, withVncCacheBust } from '../../utils/buildUrlUtils';
import { useHostSession } from '../../hooks/useHostSession';
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
  calculateVncScaling: (dimensions: { width: number; height: number }) => any;
  
  // Callbacks
  onPlayerReady: () => void;
  onVideoTimeUpdate: (time: number) => void;
  onVideoPause?: () => void;
  onCurrentSegmentChange?: (segmentUrl: string) => void;
  
  // Monitoring data props (for overlay on live video)
  monitoringAnalysis?: MonitoringAnalysis;
  subtitleAnalysis?: SubtitleAnalysis;
  languageMenuAnalysis?: LanguageMenuAnalysis;
  aiDescription?: string;
  errorTrendData?: ErrorTrendData;
  analysisTimestamp?: string;
  isAIAnalyzing?: boolean;

  // Reports the real rendered stream box (page coordinates) as it's measured, so callers
  // that position overlays on top of the video (e.g. the Android mobile tap/element
  // overlay) can use the actual box instead of the pre-render size estimate.
  onMeasuredAreaChange?: (rect: { width: number; height: number; x: number; y: number }) => void;
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
  isMuted,
  isMobileModel,
  showRemote,
  showWeb,
  finalStreamContainerDimensions,
  calculateVncScaling,
  onPlayerReady,
  onVideoTimeUpdate,
  onVideoPause,
  onCurrentSegmentChange,
  // Monitoring props
  monitoringAnalysis,
  subtitleAnalysis,
  languageMenuAnalysis,
  aiDescription,
  errorTrendData,
  analysisTimestamp,
  isAIAnalyzing,
  onMeasuredAreaChange,
}) => {
  // VNC archive mode: override streamUrl to use HLS (same as screenshot logic)
  const isVncDevice = device?.device_model === 'host_vnc';
  const audioSupported = !isVncDevice;
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

  // BUG-0107 step 2: the proxy's auth_request gate rejects the iframe's navigation to
  // /host/<name>/vnc_lite.html without this cookie. Must be set BEFORE the iframe is
  // given a src, so the live VNC iframe only renders once the mint call resolves. Not
  // keepAlive: the websocket handshake is the only request the gate ever sees, the
  // connection then persists independent of cookie expiry (unlike the HLS companion
  // player below, which is gated internally by HLSVideoPlayer itself).
  const isLiveVnc = isVncDevice && isLiveMode && !!effectiveStreamUrl;
  const vncSessionReady = useHostSession(isLiveVnc ? effectiveStreamUrl : null, false);
  // VNC scaling: the iframe keeps a fixed internal size (see calculateVncScaling) and is
  // fitted with a CSS transform, so the scale must follow the REAL stream-area size —
  // which changes whenever the remote/web side panels open (they take width from the
  // stream) or the window resizes. Measure the box instead of guessing from percentages.
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
  const streamAreaWidth = measuredStreamArea?.width || finalStreamContainerDimensions.width;
  // The measured height is the box the video actually gets. finalStreamContainerDimensions
  // caps its height to the LANDSCAPE default resolution, which on a narrow (mobile) viewport
  // collapses the player to ~width*0.56 and shrinks the video right after the poster fades.
  const streamAreaHeight = measuredStreamArea?.height || finalStreamContainerDimensions.height;
  const memoizedVncScaling = useMemo(
    () =>
      calculateVncScaling({
        width: streamAreaWidth,
        height: streamAreaHeight,
      }),
    [calculateVncScaling, streamAreaWidth, streamAreaHeight],
  );

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
      {/* Quality transition overlay - solid black to hide corrupted frames during FFmpeg restart */}
      {isQualitySwitching && (
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
              Loading {currentQuality.toUpperCase()} quality stream...
            </Typography>
            <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.7)', mt: 1 }}>
              Waiting for stable stream
            </Typography>
          </Box>
        )}
      
      {/* Content based on mode */}
      {restartMode && isControlActive ? (
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
            {vncSessionReady && (
            <iframe
              src={withVncCacheBust(effectiveStreamUrl)}
              style={{
                border: 'none',
                backgroundColor: '#000',
                display: 'block',
                pointerEvents: isControlActive ? 'auto' : 'none',
                ...memoizedVncScaling, // Apply calculated scaling
                transformOrigin: 'center center', // Override for centered layout in modal
                // Never let flexbox shrink the iframe below its fixed internal size: a
                // narrower iframe gives noVNC a viewport smaller than the remote desktop
                // and the desktop gets cropped instead of scaled (seen with panels open).
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
                  sx={{ width: '1px', height: '1px' }}
                />
              </Box>
            )}
            
            {/* Monitoring overlay for VNC - same as HLS */}
            {monitoringMode && (
              <Box
                sx={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  right: 0,
                  bottom: 0,
                  pointerEvents: 'none',
                  zIndex: 100,
                }}
              >
                <MonitoringOverlay
                  monitoringAnalysis={monitoringAnalysis || undefined}
                  subtitleAnalysis={subtitleAnalysis}
                  languageMenuAnalysis={languageMenuAnalysis}
                  consecutiveErrorCounts={errorTrendData || undefined}
                  audioSupported={audioSupported}
                  showSubtitles={!!subtitleAnalysis}
                  showLanguageMenu={!!languageMenuAnalysis}
                  analysisTimestamp={analysisTimestamp || undefined}
                  isAIAnalyzing={isAIAnalyzing}
                />
              </Box>
            )}
          </Box>
        ) : (
          <EnhancedHLSPlayer
            deviceId={device?.device_id || 'device1'}
            hostName={host.host_name}
            host={host}
            streamUrl={effectiveStreamUrl}
            width="100%"
            height={streamAreaHeight}
            muted={isMuted}
            isLiveMode={isLiveMode}
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
          />
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

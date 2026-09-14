import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { Box, Typography, CircularProgress } from '@mui/material';
import { HLSVideoPlayer } from '../common/HLSVideoPlayer';
import { MonitoringOverlay } from '../monitoring/MonitoringOverlay';
import { useStream } from '../../hooks/controller';
import { buildStreamUrl } from '../../utils/buildUrlUtils';
import { EnhancedHLSPlayerProps } from './EnhancedHLSPlayer.types';
import { useArchivePlayer } from './hooks/useArchivePlayer';
import { useLiveTranscriptFeed } from './hooks/useLiveTranscriptFeed';
import { useTranscriptPlayer } from './hooks/useTranscriptPlayer';
import { LiveTranscriptRail } from './overlays/LiveTranscriptRail';
import { TimelineOverlay } from './overlays/TimelineOverlay';
import { TranscriptOverlay } from './overlays/TranscriptOverlay';
import { DEFAULT_DEVICE_RESOLUTION } from '../../config/deviceResolutions';

export const EnhancedHLSPlayer: React.FC<EnhancedHLSPlayerProps> = ({
  deviceId,
  hostName,
  host,
  streamUrl: providedStreamUrl,
  width = '100%',
  height = 400,
  muted = true,
  className,
  isLiveMode: externalIsLiveMode,
  quality = 'sd',
  shouldPause = false,
  onPlayerReady,
  onVideoTimeUpdate,
  onCurrentSegmentChange,

  showLiveTranscriptRail = false,

  monitoringMode = false,
  monitoringAnalysis,
  subtitleAnalysis,
  languageMenuAnalysis,
  aiDescription,
  errorTrendData,
  analysisTimestamp,
  isAIAnalyzing = false,
  archiveSeek,
  hideTimelineOverlay = false,
  freezeArchiveFrame = false,
}) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const dubbedAudioRef = useRef<HTMLAudioElement>(null); // Dubbed audio player
  const videoContainerRef = useRef<HTMLDivElement>(null); // Container ref for timeline positioning
  const [internalIsLiveMode] = useState(true);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);
  const [isTransitioning, setIsTransitioning] = useState(false);
  const qualityTimestampRef = useRef<number>(Date.now());
  const [isAtLiveEdge, setIsAtLiveEdge] = useState(true);
  const liveEdgeTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const [liveBufferSeconds, setLiveBufferSeconds] = useState(0);
  const [liveSliderPosition, setLiveSliderPosition] = useState(150);
  const maxBufferSecondsRef = useRef<number>(0);
  // Rail starts collapsed — the vertical TRANSCRIPT tab reopens it on demand.
  // Keeping it closed by default also avoids polling the chunk JSON until asked.
  const [liveRailDismissed, setLiveRailDismissed] = useState(true);
  
  const isLiveMode = externalIsLiveMode !== undefined ? externalIsLiveMode : internalIsLiveMode;
  
  const prevIsLiveMode = useRef(isLiveMode);
  const prevQuality = useRef(quality);
  
  useEffect(() => {
    if (prevQuality.current !== quality) {
      qualityTimestampRef.current = Date.now();
      prevQuality.current = quality;
    }
  }, [quality]);

  const { streamUrl: hookStreamUrl } = useStream({
    host: host || {
      host_name: hostName,
      host_url: `http://${hostName}:6109`,
      host_port: 6109,
      devices: [],
      device_count: 0,
      status: 'online',
      last_seen: Date.now(),
      registered_at: new Date().toISOString(),
      system_stats: {
        cpu_percent: 0,
        memory_percent: 0,
        disk_percent: 0,
        platform: 'linux',
        architecture: 'x86_64',
        python_version: '3.9'
      },
      isLocked: false
    },
    device_id: deviceId,
  });

  const archive = useArchivePlayer({
    isLiveMode,
    providedStreamUrl,
    hookStreamUrl: hookStreamUrl || undefined,
    host,
    deviceId,
    isTransitioning,
    videoRef,
    onVideoTimeUpdate,
  });

  const transcript = useTranscriptPlayer({
    isLiveMode,
    archiveMetadata: archive.archiveMetadata,
    currentManifestIndex: archive.currentManifestIndex,
    globalCurrentTime: archive.globalCurrentTime,
    providedStreamUrl,
    hookStreamUrl: hookStreamUrl || undefined,
    host,
    deviceId,
  });

  // Live transcript rail. The archive TranscriptOverlay is live-mode-blind by design
  // (show={!isLiveMode}); this covers the live side by polling the chunk JSON the
  // host writes progressively. Requires ENABLE_TRANSCRIPTION=true on that host.
  const liveTranscript = useLiveTranscriptFeed({
    isLiveMode,
    host,
    deviceId,
    enabled: showLiveTranscriptRail && !liveRailDismissed,
  });

  // External archive seek (AVQ timeline click). Apply once the archive manifest
  // is loaded; if a seek arrives before metadata is ready, hold it pending and
  // apply when the manifest lands.
  const pendingSeekRef = useRef<number | null>(null);
  const lastSeekNonceRef = useRef<number>(-1);
  useEffect(() => {
    if (archiveSeek && archiveSeek.nonce !== lastSeekNonceRef.current) {
      lastSeekNonceRef.current = archiveSeek.nonce;
      pendingSeekRef.current = archiveSeek.time;
    }
    if (
      pendingSeekRef.current != null &&
      !isLiveMode &&
      archive.archiveMetadata &&
      archive.archiveMetadata.manifests.length > 0
    ) {
      archive.handleSeek(null as any, pendingSeekRef.current);
      pendingSeekRef.current = null;
    }
  }, [archiveSeek, isLiveMode, archive.archiveMetadata, archive]);

  useEffect(() => {
    if (prevIsLiveMode.current !== isLiveMode) {
      setIsTransitioning(true);
      
      if (isLiveMode) {
        // Reset all buffer state immediately when switching to live
        setIsAtLiveEdge(true);
        setLiveBufferSeconds(0);
        setLiveSliderPosition(150);
        maxBufferSecondsRef.current = 0;
        
        archive.clearArchiveData();
        transcript.clearTranscriptData();
      }
      
      setTimeout(() => {
        setIsTransitioning(false);
      }, 100);
      
      prevIsLiveMode.current = isLiveMode;
    }
  }, [isLiveMode, archive, transcript]);

  // Track play/pause state for UI only (no AI analysis on pause)
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const handlePlay = () => {
      setIsPlaying(true);
    };

    const handlePause = () => {
      setIsPlaying(false);
    };

    video.addEventListener('play', handlePlay);
    video.addEventListener('pause', handlePause);

    return () => {
      video.removeEventListener('play', handlePlay);
      video.removeEventListener('pause', handlePause);
    };
  }, []);

  const streamUrl = useMemo(() => {
    let url: string;
    
    if (isLiveMode) {
      if (providedStreamUrl) {
        url = providedStreamUrl.replace(/\/(segments\/)?(output|archive.*?)\.m3u8$/, '/segments/output.m3u8');
      } else if (hookStreamUrl) {
        url = hookStreamUrl.replace(/\/(segments\/)?(output|archive.*?)\.m3u8$/, '/segments/output.m3u8');
      } else {
        url = buildStreamUrl(host, deviceId);
      }
    }
    else if (archive.archiveMetadata && archive.archiveMetadata.manifests.length > 0) {
      const currentManifest = archive.archiveMetadata.manifests[archive.currentManifestIndex];
      if (currentManifest) {
        const baseUrl = providedStreamUrl || hookStreamUrl || buildStreamUrl(host, deviceId, 'archive');
        const chunkPath = currentManifest.name;
        url = baseUrl.replace(/\/(segments\/)?(output|archive.*?)\.m3u8$/, `/segments/${chunkPath}`);
      } else {
        const baseUrl = providedStreamUrl || hookStreamUrl || buildStreamUrl(host, deviceId, 'archive');
        const firstHour = archive.availableHours.length > 0 ? archive.availableHours[0] : 0;
        url = baseUrl.replace(/\/(segments\/)?(output|archive.*?)\.m3u8$/, `/segments/${firstHour}/chunk_10min_0.mp4`);
      }
    }
    else {
      const baseUrl = providedStreamUrl || hookStreamUrl || buildStreamUrl(host, deviceId, 'archive');
      const firstHour = archive.availableHours.length > 0 ? archive.availableHours[0] : 0;
      url = baseUrl.replace(/\/(segments\/)?(output|archive.*?)\.m3u8$/, `/segments/${firstHour}/chunk_10min_0.mp4`);
    }
    
    const separator = url.includes('?') ? '&' : '?';
    url = `${url}${separator}q=${quality}&t=${qualityTimestampRef.current}`;
    
    return url;
  }, [providedStreamUrl, hookStreamUrl, isLiveMode, deviceId, archive.archiveMetadata, archive.currentManifestIndex, quality, archive.availableHours, host]);

  const togglePlayPause = () => {
    if (videoRef.current) {
      if (isPlaying) {
        videoRef.current.pause();
      } else {
        videoRef.current.play();
      }
      setIsPlaying(!isPlaying);
    }
  };

  const handleLiveSliderChange = useCallback((_event: Event | React.SyntheticEvent, newValue: number | number[]) => {
    const value = Array.isArray(newValue) ? newValue[0] : newValue;
    const minAllowed = Math.max(0, 150 - liveBufferSeconds);
    const clampedValue = Math.max(value, minAllowed);
    setLiveSliderPosition(clampedValue);
    archive.handleSliderChange(_event, clampedValue);
    setIsAtLiveEdge(clampedValue >= 145);
  }, [archive, liveBufferSeconds]);

  const handleLiveSeek = useCallback((_event: Event | React.SyntheticEvent, newValue: number | number[]) => {
    if (!videoRef.current) return;
    
    const value = Array.isArray(newValue) ? newValue[0] : newValue;
    const video = videoRef.current;
    
    if (video.buffered.length > 0) {
      const buffered = video.buffered;
      const bufferEnd = buffered.end(buffered.length - 1);
      const bufferStart = buffered.start(0);
      
      const secondsBehind = 150 - value;
      const targetTime = bufferEnd - secondsBehind;
      
      video.currentTime = Math.max(bufferStart, Math.min(targetTime, bufferEnd));
      setLiveSliderPosition(value);
      
      if (value >= 145) {
        video.currentTime = bufferEnd - 0.5;  // ✅ More aggressive live edge (was 1s)
        setLiveSliderPosition(150);
      }
    }
    
    archive.handleSeek(_event, newValue);
  }, [archive, videoRef]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const handleTimeUpdate = () => {
      setCurrentTime(video.currentTime);
      
      if (isLiveMode && video.buffered.length > 0) {
        const buffered = video.buffered;
        const bufferEnd = buffered.end(buffered.length - 1);
        const bufferStart = buffered.start(0);
        const totalBuffer = bufferEnd - bufferStart;
        const latency = bufferEnd - video.currentTime;
        const atLiveEdge = latency < 2;  // ✅ Tighter live edge detection (was 3s)
        
        // Track maximum buffer size (DVR window) - only increase, never decrease
        // This represents the maximum seekable range, not the instantaneous buffered range
        // Cap at 150s since that's our live slider maximum range
        if (totalBuffer > maxBufferSecondsRef.current && maxBufferSecondsRef.current < 150) {
          const cappedBuffer = Math.min(totalBuffer, 150);
          maxBufferSecondsRef.current = cappedBuffer;
          setLiveBufferSeconds(cappedBuffer);
        }
        
        if (atLiveEdge !== isAtLiveEdge) {
          setIsAtLiveEdge(atLiveEdge);
        }
      }
      
      if (!isLiveMode) {
        archive.updateTimeTracking(video);
      }
    };
    
    const handleDurationChange = () => {
      setDuration(video.duration);
    };

    const handlePlay = () => setIsPlaying(true);
    const handlePause = () => setIsPlaying(false);

    video.addEventListener('timeupdate', handleTimeUpdate);
    video.addEventListener('durationchange', handleDurationChange);
    video.addEventListener('play', handlePlay);
    video.addEventListener('pause', handlePause);
    video.addEventListener('error', archive.handleVideoError);

    return () => {
      video.removeEventListener('timeupdate', handleTimeUpdate);
      video.removeEventListener('durationchange', handleDurationChange);
      video.removeEventListener('play', handlePlay);
      video.removeEventListener('pause', handlePause);
      video.removeEventListener('error', archive.handleVideoError);
      
      if (liveEdgeTimeoutRef.current) {
        clearTimeout(liveEdgeTimeoutRef.current);
      }
    };
  }, [isLiveMode, archive, isAtLiveEdge]);

  // Seek to live edge after stream is ready (only for live mode)
  useEffect(() => {
    if (!isLiveMode || isTransitioning) return;
    
    const video = videoRef.current;
    if (!video) return;
    
    // Wait for the live stream to be loaded and have buffered data
    const seekToLiveWhenReady = () => {
      if (video.readyState >= 2 && video.buffered.length > 0) {
        const buffered = video.buffered;
        const bufferEnd = buffered.end(buffered.length - 1);
        video.currentTime = bufferEnd - 0.5; // Seek to near live edge
      }
    };
    
    // Try immediately if already loaded
    if (video.readyState >= 2 && video.buffered.length > 0) {
      seekToLiveWhenReady();
    } else {
      // Wait for data to be available
      const handleCanPlay = () => {
        setTimeout(seekToLiveWhenReady, 500); // Small delay to ensure buffer is populated
      };
      video.addEventListener('canplay', handleCanPlay, { once: true });
      
      return () => {
        video.removeEventListener('canplay', handleCanPlay);
      };
    }
  }, [isLiveMode, isTransitioning, streamUrl]);

  // Freeze-frame mode (AVQ inspector): never auto-play in archive, and immediately
  // pause if anything starts playback so the seeked still frame is held.
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !freezeArchiveFrame || isLiveMode) return;
    const pauseBack = () => video.pause();
    video.addEventListener('play', pauseBack);
    if (!video.paused) video.pause();
    return () => video.removeEventListener('play', pauseBack);
  }, [freezeArchiveFrame, isLiveMode, streamUrl]);

  // Auto-play archive mode after video loads AND archive is ready
  useEffect(() => {
    if (freezeArchiveFrame) return;
    if (!isLiveMode && videoRef.current && !isTransitioning && archive.archiveMetadata) {
      const video = videoRef.current;
      
      // Wait for video to be loaded and ready, then auto-play
      const tryPlay = () => {
        if (video.readyState >= 2) { // HAVE_CURRENT_DATA or higher
          // Don't seek to 0 - causes interruption. Just play from wherever it loaded.
          video.play().catch(() => {
            // Auto-play failed (likely browser policy)
          });
        }
      };

      // Small delay to ensure everything is initialized
      const timer = setTimeout(() => {
        if (video.readyState >= 2) {
          tryPlay();
        } else {
          video.addEventListener('loadeddata', tryPlay, { once: true });
        }
      }, 100);

      return () => {
        clearTimeout(timer);
        video.removeEventListener('loadeddata', tryPlay);
      };
    }
  }, [isLiveMode, streamUrl, isTransitioning, archive.archiveMetadata, freezeArchiveFrame]);

  // Dubbed audio sync and control with retry on error
  useEffect(() => {
    const video = videoRef.current;
    const dubbedAudio = dubbedAudioRef.current;
    if (!video || !dubbedAudio) return;

    const hasDubbedAudio = !!transcript.dubbedAudioUrl;
    console.log(`[@EnhancedHLSPlayer] Dubbed audio URL changed:`, transcript.dubbedAudioUrl, `| Will mute video: ${hasDubbedAudio}`);

    if (hasDubbedAudio) {
      // Mute video, play dubbed audio (respecting muted prop from modal)
      video.muted = true;
      dubbedAudio.muted = muted; // Apply muted state from modal to dubbed audio
      dubbedAudio.src = transcript.dubbedAudioUrl || '';
      dubbedAudio.currentTime = video.currentTime;
      
      console.log(`[@EnhancedHLSPlayer] ✅ Video muted, dubbed audio loaded (dubbed audio muted: ${muted})`);
      
      // Handle audio load errors with retry
      let retryCount = 0;
      const maxRetries = 2;
      
      const handleAudioError = () => {
        if (retryCount < maxRetries) {
          retryCount++;
          console.log(`[@EnhancedHLSPlayer] ⚠️ Audio failed to load, retrying... (${retryCount}/${maxRetries})`);
          setTimeout(() => {
            dubbedAudio.load();
            dubbedAudio.currentTime = video.currentTime;
            if (!video.paused) {
              dubbedAudio.play().catch(() => {
                console.error(`[@EnhancedHLSPlayer] Retry ${retryCount} failed`);
              });
            }
          }, 500 * retryCount); // Progressive delay: 500ms, 1000ms
        } else {
          console.error(`[@EnhancedHLSPlayer] ❌ Audio failed to load after ${maxRetries} retries`);
        }
      };
      
      const handleAudioCanPlay = () => {
        console.log(`[@EnhancedHLSPlayer] 🎵 Audio ready to play`);
        if (!video.paused) {
          dubbedAudio.play().catch((err) => {
            console.error(`[@EnhancedHLSPlayer] Failed to play dubbed audio:`, err);
          });
        }
      };
      
      dubbedAudio.addEventListener('error', handleAudioError);
      dubbedAudio.addEventListener('canplay', handleAudioCanPlay);
      
      // Sync playback state
      if (!video.paused) {
        dubbedAudio.play().catch((err) => {
          console.error(`[@EnhancedHLSPlayer] Failed to play dubbed audio:`, err);
        });
      }
      
      return () => {
        dubbedAudio.removeEventListener('error', handleAudioError);
        dubbedAudio.removeEventListener('canplay', handleAudioCanPlay);
      };
    } else {
      // Restore original video audio
      video.muted = muted;
      dubbedAudio.pause();
      dubbedAudio.src = '';
      dubbedAudio.muted = false; // Reset dubbed audio muted state
      console.log(`[@EnhancedHLSPlayer] Video audio restored (unmuted: ${!muted})`);
    }
  }, [transcript.dubbedAudioUrl, muted]);

  // Sync dubbed audio with video playback
  useEffect(() => {
    const video = videoRef.current;
    const dubbedAudio = dubbedAudioRef.current;
    if (!video || !dubbedAudio || !transcript.dubbedAudioUrl) return;

    const syncAudio = () => {
      // Keep audio synced with video (tolerance: 0.3s)
      if (Math.abs(dubbedAudio.currentTime - video.currentTime) > 0.3) {
        dubbedAudio.currentTime = video.currentTime;
      }
    };

    const handleVideoPlay = () => {
      dubbedAudio.play().catch(() => {
        // Failed to play dubbed audio
      });
    };

    const handleVideoPause = () => {
      dubbedAudio.pause();
    };

    const handleVideoSeeking = () => {
      dubbedAudio.currentTime = video.currentTime;
    };

    // Sync every 100ms
    const syncInterval = setInterval(syncAudio, 100);

    video.addEventListener('play', handleVideoPlay);
    video.addEventListener('pause', handleVideoPause);
    video.addEventListener('seeking', handleVideoSeeking);

    return () => {
      clearInterval(syncInterval);
      video.removeEventListener('play', handleVideoPlay);
      video.removeEventListener('pause', handleVideoPause);
      video.removeEventListener('seeking', handleVideoSeeking);
    };
  }, [transcript.dubbedAudioUrl]);

  // Generate layoutConfig based on device model - consistent with RecHostPreview
  const layoutConfig = useMemo(() => {
    if (!host) return undefined;
    
    // Find device to get model
    const device = host.devices?.find((d) => d.device_id === deviceId);
    const deviceModel = device?.device_model || 'unknown';
    const isMobile = deviceModel?.includes('mobile') || deviceModel === 'android_mobile';
    
    return {
      minHeight: '400px',
      aspectRatio: `${DEFAULT_DEVICE_RESOLUTION.width}/${DEFAULT_DEVICE_RESOLUTION.height}`,
      objectFit: 'contain' as 'cover' | 'contain',
      isMobileModel: isMobile,
    };
  }, [host, deviceId]);

  const isHostVncDevice = useMemo(() => {
    if (!host) return false;
    const device = host.devices?.find((d) => d.device_id === deviceId);
    return device?.device_model === 'host_vnc';
  }, [host, deviceId]);

  return (
    <Box className={className} sx={{ width, position: 'relative' }}>
      <style>
        {`
          @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.5; }
            100% { opacity: 1; }
          }
        `}
      </style>
      
      <Box ref={videoContainerRef} sx={{ position: 'relative', height, overflow: 'visible' }}>
        {/* Hidden dubbed audio player (synced with video) */}
        <audio ref={dubbedAudioRef} style={{ display: 'none' }} />
        
        {!isTransitioning && (!archive.isCheckingAvailability && (isLiveMode || archive.availableHours.length > 0)) ? (
          <HLSVideoPlayer
            key={`${isLiveMode ? 'live' : 'archive'}`}
            streamUrl={streamUrl}
            isStreamActive={true}
            videoElementRef={videoRef}
            muted={muted}
            isArchiveMode={!isLiveMode}
            shouldPause={shouldPause}
            layoutConfig={layoutConfig}
            sx={{ width: '100%', height: '100%' }}
            onPlayerReady={onPlayerReady}
            onCurrentSegmentChange={onCurrentSegmentChange}
          />
        ) : (
          <Box
            sx={{
              width: '100%',
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: 'black',
              color: 'white',
            }}
          >
            {archive.isCheckingAvailability ? (
              <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                <CircularProgress sx={{ color: 'white' }} />
                <Typography>Checking available archive hours...</Typography>
              </Box>
            ) : archive.availableHours.length === 0 && !isLiveMode ? (
              <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                <Typography>No archive hours available</Typography>
                <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.6)' }}>
                  Switch back to Live mode or check again later
                </Typography>
              </Box>
            ) : (
              <Typography>Switching mode...</Typography>
            )}
          </Box>
        )}

        {/* Monitoring overlay - only available in Live mode */}
        {monitoringMode && isLiveMode && (
          <Box
            sx={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              height: '100%',
              pointerEvents: 'none',
              zIndex: 100,
            }}
          >
            <MonitoringOverlay
              monitoringAnalysis={monitoringAnalysis || undefined}
              subtitleAnalysis={subtitleAnalysis}
              languageMenuAnalysis={languageMenuAnalysis}
              consecutiveErrorCounts={errorTrendData || undefined}
              audioSupported={!isHostVncDevice}
              showSubtitles={!!subtitleAnalysis}
              showLanguageMenu={!!languageMenuAnalysis}
              analysisTimestamp={analysisTimestamp || undefined}
              isAIAnalyzing={isAIAnalyzing}
            />

            {aiDescription && (
              <Box
                sx={{
                  position: 'absolute',
                  top: 16,
                  left: '50%',
                  transform: 'translateX(-50%)',
                  maxWidth: '60%',
                  minWidth: 300,
                  p: 1,
                  backgroundColor: 'rgba(0, 0, 0, 0.75)',
                  borderRadius: 1,
                  border: '1px solid rgba(255, 255, 255, 0.2)',
                  textAlign: 'center',
                  zIndex: 30,
                  pointerEvents: 'none',
                }}
              >
                <Typography
                  variant="body2"
                  sx={{
                    color: '#ffffff',
                    fontSize: '0.7rem',
                    lineHeight: 1.2,
                    fontWeight: 400,
                    display: '-webkit-box',
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: 'vertical',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {aiDescription}
                </Typography>
              </Box>
            )}
          </Box>
        )}

        <TranscriptOverlay
          transcriptText={transcript.getCurrentTranscriptText()}
          selectedLanguage={transcript.selectedLanguage}
          availableLanguages={transcript.availableLanguages}
          availableDubbedLanguages={transcript.availableDubbedLanguages}
          onLanguageChange={transcript.handleLanguageChange}
          isTranslating={transcript.isTranslating}
          show={!isLiveMode}
          hasMp3={transcript.hasMp3}
          mp3Url={transcript.mp3Url}
        />

        <LiveTranscriptRail
          lines={liveTranscript.lines}
          show={showLiveTranscriptRail && isLiveMode && !liveRailDismissed}
          onClose={() => setLiveRailDismissed(true)}
        />

        {showLiveTranscriptRail && isLiveMode && liveRailDismissed && (
          <Box
            onClick={() => setLiveRailDismissed(false)}
            sx={{
              position: 'absolute',
              top: '50%',
              right: 0,
              transform: 'translateY(-50%)',
              px: 0.5,
              py: 1.5,
              backgroundColor: 'rgba(0, 0, 0, 0.85)',
              color: 'rgba(255, 255, 255, 0.7)',
              border: '1px solid rgba(255, 255, 255, 0.2)',
              borderRight: 'none',
              borderRadius: '4px 0 0 4px',
              cursor: 'pointer',
              zIndex: 1250,
              writingMode: 'vertical-rl',
              fontSize: '0.65rem',
              fontWeight: 600,
              letterSpacing: 1,
              userSelect: 'none',
              '&:hover': { color: 'white', backgroundColor: 'rgba(0, 0, 0, 0.95)' },
            }}
          >
            TRANSCRIPT
          </Box>
        )}

        {!hideTimelineOverlay && (
        <TimelineOverlay
          isLiveMode={isLiveMode}
          isPlaying={isPlaying}
          currentTime={currentTime}
          duration={duration}
          isAtLiveEdge={isAtLiveEdge}
          liveBufferSeconds={liveBufferSeconds}
          liveSliderPosition={liveSliderPosition}
          globalCurrentTime={archive.globalCurrentTime}
          isDraggingSlider={archive.isDraggingSlider}
          dragSliderValue={archive.dragSliderValue}
          archiveMetadata={archive.archiveMetadata}
          availableHours={archive.availableHours}
          continuousStartTime={archive.continuousStartTime}
          continuousEndTime={archive.continuousEndTime}
          hourMarks={archive.hourMarks}
          errorChunkIndices={archive.errorChunkIndices}
          videoRef={videoRef}
          onTogglePlayPause={togglePlayPause}
          onSliderChange={isLiveMode ? handleLiveSliderChange : archive.handleSliderChange}
          onSeek={isLiveMode ? handleLiveSeek : archive.handleSeek}
          show={!isTransitioning}
          currentManifestIndex={archive.currentManifestIndex}
          containerRef={videoContainerRef}
        />
        )}
      </Box>
    </Box>
  );
};

import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import { Box, Typography, IconButton } from '@mui/material';
import React, { useRef, useEffect, useState, useCallback } from 'react';

import { StreamViewerLayoutConfig } from '../../config/layoutConfig';
import { useHostSession } from '../../hooks/useHostSession';
import { isGatedHostPath } from '../../utils/buildUrlUtils';

// Proxy for Hls.isSupported() usable before the dynamic hls.js import. When MSE is
// available, hls.js is the ONLY valid engine for .m3u8: Chromium answers
// canPlayType('application/vnd.apple.mpegurl') with 'maybe' but its native demuxer
// cannot parse these live playlists (DEMUXER_ERROR_COULD_NOT_PARSE), so pointing
// <video>.src at a playlist wedges the player until remount. Native HLS is reserved
// for MSE-less browsers (iOS Safari) and MP4 files.
const MSE_SUPPORTED = typeof window !== 'undefined' && 'MediaSource' in window;

interface HLSVideoPlayerProps {
  streamUrl?: string;
  isStreamActive?: boolean;
  isCapturing?: boolean;
  sx?: any;
  videoElementRef?: React.RefObject<HTMLVideoElement>;
  model?: string;
  layoutConfig?: StreamViewerLayoutConfig;
  isExpanded?: boolean;
  muted?: boolean; // Add muted prop
  isArchiveMode?: boolean; // Add archive mode prop
  shouldPause?: boolean; // Pause player to show last frame (during quality transition)
  onRestartRequest?: () => void; // Callback to expose restart functionality
  onPlayerReady?: () => void; // Callback when player loads successfully
  onCurrentSegmentChange?: (segmentUrl: string) => void; // Callback when current segment changes
}

/**
 * HLS Video Player Component
 *
 * Universal video player supporting both HLS streams and MP4 files.
 * Automatically detects format and uses appropriate playback method.
 *
 * Features:
 * - HLS live streaming with low latency configuration
 * - MP4 video playback for recorded content
 * - Native fallback for Safari
 * - Auto-retry with fallback logic
 * - User interaction handling for autoplay
 * - Robust error handling and recovery
 * - CPU-efficient latency correction (only when needed)
 */
export function HLSVideoPlayer({
  streamUrl: rawStreamUrl,
  isStreamActive = false,
  isCapturing = false,
  sx = {},
  videoElementRef,
  model,
  layoutConfig,
  muted = true, // Default to muted for autoplay compliance
  isArchiveMode = false, // Default to live mode
  shouldPause = false, // Default to not paused
  onRestartRequest, // New prop for external restart trigger
  onPlayerReady, // Callback when player loads successfully
  onCurrentSegmentChange, // Callback when current segment changes
}: HLSVideoPlayerProps) {
  // BUG-0107 step 2: /host/<name>/stream/... now sits behind the proxy's auth_request
  // gate. This is the one sink every live/archive stream path converges on (direct,
  // via useStream, or via EnhancedHLSPlayer's own fallback chain) — withholding the URL
  // here until the session cookie is confirmed covers all of them without touching each
  // call site. `keepAlive: true` because HLS re-fetches segments for as long as playback
  // runs, unlike VNC's one-time handshake — a long-running view needs the cookie refreshed
  // periodically or it 401s mid-stream once the short TTL elapses. No-op (and no render
  // delay) for any URL the gate doesn't cover.
  const hostSessionReady = useHostSession(rawStreamUrl, true);
  const streamUrl = hostSessionReady ? rawStreamUrl : undefined;

  // Minting the cookie is only half the job: the browser also has to SEND it. On the web
  // that is automatic — the stream is same-origin with the page. Inside the mobile app it
  // is not: the Capacitor shell serves this bundle from `https://localhost`, so every
  // stream request is cross-origin, and a cross-origin fetch omits cookies unless it opts
  // in. hls.js defaults `withCredentials` to false and `crossOrigin="anonymous"` means
  // "CORS, no credentials" outright — so the APK minted a cookie it then never presented,
  // and every manifest and segment came back 401. Opt in, but only for URLs the gate
  // actually covers: a credentialed request also forbids a wildcard
  // `Access-Control-Allow-Origin`, which is still what ungated public assets serve.
  const streamIsGated = isGatedHostPath(rawStreamUrl);

  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<any>(null);
  // Fatal-media-error bookkeeping for hls.recoverMediaError(): first strike recovers
  // in place, second inside the window also swaps the audio codec, third falls through
  // to the destructive restart. Time-windowed so isolated glitches don't accumulate.
  const mediaRecoveryRef = useRef({ lastAt: 0, swappedAudio: false });
  const [streamError, setStreamError] = useState<string | null>(null);
  const [streamLoaded, setStreamLoaded] = useState(false);
  const [currentStreamUrl, setCurrentStreamUrl] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const [requiresUserInteraction, setRequiresUserInteraction] = useState(false);
  const [useNativePlayer, setUseNativePlayer] = useState(false);
  const [isVideoReady, setIsVideoReady] = useState(false);
  const [segmentFailureCount, setSegmentFailureCount] = useState(0);
  const [ffmpegStuck, setFfmpegStuck] = useState(false);
  const [visibleError, setVisibleError] = useState<string | null>(null); // Debounced error shown to user
  const errorDebounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const maxRetries = 5;
  const maxSegmentFailures = 10; // Stop after 10 consecutive segment failures
  const retryDelay = 6000;
  const errorDisplayDelay = 10000; // Only show error UI after 10s of sustained errors
  const lastInitTime = useRef<number>(0);
  // Pending re-init scheduled because a call hit the throttle window. Deduped so a
  // burst of throttled calls schedules only one retry. Without this, a legitimate
  // URL change (e.g. an auto quality switch landing <1s after the previous init)
  // is silently dropped while the URL-changed effect has already advanced its ref,
  // leaving the player stuck on "Loading stream..." forever.
  const pendingInitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // True while an init is mid-flight (during the async hls.js import + setup window).
  // initializeStream calls setStreamLoaded(false) before awaiting the dynamic import;
  // that await yields, React flushes, and the "stream activated while not loaded"
  // effect re-fires initializeStream during the gap — the source of the reload loop.
  // This flag rejects those re-entrant calls.
  const initInFlightRef = useRef(false);
  // Stale-closure-safe mirror of streamLoaded. The throttle reschedule and the
  // re-fired init effects capture an old initializeStream closure; reading state
  // there is stale, so the "already loaded" guard must read refs instead.
  const streamLoadedRef = useRef(false);
  // The streamUrl that has actually finished loading and is playing. Set on
  // MANIFEST_PARSED / native loadedmetadata|canplay, cleared on cleanup/error.
  // Distinct from currentStreamUrl, which the URL-changed effect advances eagerly
  // (before load completes), so currentStreamUrl can't tell "loaded" from "loading".
  const loadedStreamUrlRef = useRef<string | null>(null);

  // Debounce error display - only show error UI after sustained errors (10s)
  // Terminal errors (ffmpegStuck, manifest 404) show immediately
  useEffect(() => {
    if (errorDebounceTimer.current) {
      clearTimeout(errorDebounceTimer.current);
      errorDebounceTimer.current = null;
    }

    if (!streamError) {
      // Error cleared (recovered) - hide immediately
      setVisibleError(null);
      return;
    }

    if (ffmpegStuck || streamError.includes('manifest not found') || streamError.includes('initialization failed')) {
      // Terminal errors show immediately
      setVisibleError(streamError);
      return;
    }

    // Transient errors - delay display by 10s
    errorDebounceTimer.current = setTimeout(() => {
      setVisibleError(streamError);
    }, errorDisplayDelay);

    return () => {
      if (errorDebounceTimer.current) {
        clearTimeout(errorDebounceTimer.current);
        errorDebounceTimer.current = null;
      }
    };
  }, [streamError, ffmpegStuck, errorDisplayDelay]);

  // Add native HLS support detection
  const [supportsNativeHLS, setSupportsNativeHLS] = useState(false);

  useEffect(() => {
    console.log('[@component:HLSVideoPlayer] Component mounted with props:', {
      streamUrl,
      isStreamActive,
      isCapturing,
      model,
      layoutConfig,
      hasVideoRef: !!videoRef.current,
    });

    return () => {
      console.log('[@component:HLSVideoPlayer] Component unmounting');
    };
  }, []);



  useEffect(() => {
    if (videoElementRef && videoRef.current) {
      (videoElementRef as any).current = videoRef.current;
    }
  }, [videoElementRef]);

  // Add effect for detecting native HLS support
  useEffect(() => {
    const tempVideo = document.createElement('video');
    setSupportsNativeHLS(tempVideo.canPlayType('application/vnd.apple.mpegurl') !== '');
  }, []);

  // Keep streamLoadedRef in sync so stale-closure callers (throttle reschedule,
  // re-fired effects) can read the current load state without bypassing the guard.
  useEffect(() => {
    streamLoadedRef.current = streamLoaded;
  }, [streamLoaded]);

  const cleanupStream = useCallback(() => {
    console.log('[@component:HLSVideoPlayer] Starting aggressive stream cleanup');
    
    // Clean up native playback event listeners first
    if (videoRef.current && nativePlaybackHandlersRef.current) {
      const video = videoRef.current;
      const handlers = nativePlaybackHandlersRef.current;
      
      video.removeEventListener('loadedmetadata', handlers.loadedmetadata);
      video.removeEventListener('error', handlers.error);
      video.removeEventListener('canplay', handlers.canplay);
      
      nativePlaybackHandlersRef.current = null;
      console.log('[@component:HLSVideoPlayer] Native playback event listeners removed during cleanup');
    }
    
    if (hlsRef.current) {
      try {
        // More aggressive HLS cleanup
        const hls = hlsRef.current;
        
        // Stop loading first
        hls.stopLoad();

        // Detach media BEFORE removing listeners. detachMedia() fires MEDIA_DETACHING
        // synchronously, which is what lets hls.js's internal controllers remove their
        // own 'seeking'/'seeked' DOM listeners from the <video>. If we removeAllListeners()
        // first, those controllers are already unsubscribed, the DOM listeners are never
        // cleaned up, and after destroy() they fire on the next seek with a nulled logger
        // -> "this.log is not a function" (one orphaned set leaked per reinit).
        if (videoRef.current) {
          hls.detachMedia();
        }

        // Now safe to remove our own event listeners and destroy the instance
        hls.removeAllListeners();
        hls.destroy();
        
        console.log('[@component:HLSVideoPlayer] HLS instance destroyed successfully');
      } catch (error) {
        console.warn('[@component:HLSVideoPlayer] Error destroying HLS instance:', error);
      }
      hlsRef.current = null;
    }

    if (videoRef.current) {
      const video = videoRef.current;
      
      // Pause and clear video
      video.pause();
      
      // Remove all event listeners from video element
      video.removeAttribute('src');
      video.removeAttribute('srcObject');
      
      // Clear any media source
      if (video.srcObject) {
        video.srcObject = null;
      }
      
      // Force reload to clear any cached data
      video.load();
      
      console.log('[@component:HLSVideoPlayer] Video element cleaned up');
    }

    // Reset all state
    loadedStreamUrlRef.current = null;
    setStreamLoaded(false);
    setStreamError(null);
    setSegmentFailureCount(0);
    setFfmpegStuck(false);
    setCurrentStreamUrl(null);
    
    console.log('[@component:HLSVideoPlayer] Stream cleanup completed');
  }, []);

  const attemptPlay = useCallback(() => {
    if (!videoRef.current) return;

    const playPromise = videoRef.current.play();
    if (playPromise !== undefined) {
      playPromise.catch((err) => {
        console.warn('[@component:HLSVideoPlayer] Autoplay failed:', err.message);
        if (err.name === 'NotAllowedError' || err.message.includes('user interaction')) {
          setRequiresUserInteraction(true);
        } else {
          console.warn('[@component:HLSVideoPlayer] Play failed, but continuing:', err.message);
        }
      });
    }
  }, []);

  const handleUserPlay = useCallback(() => {
    setRequiresUserInteraction(false);
    attemptPlay();
  }, [attemptPlay]);

  const nativePlaybackHandlersRef = useRef<{
    loadedmetadata: () => void;
    error: (e: any) => void;
    canplay: () => void;
  } | null>(null);

  const cleanupNativePlayback = useCallback(() => {
    if (videoRef.current && nativePlaybackHandlersRef.current) {
      const video = videoRef.current;
      const handlers = nativePlaybackHandlersRef.current;
      
      video.removeEventListener('loadedmetadata', handlers.loadedmetadata);
      video.removeEventListener('error', handlers.error);
      video.removeEventListener('canplay', handlers.canplay);
      
      nativePlaybackHandlersRef.current = null;
      console.log('[@component:HLSVideoPlayer] Native playback event listeners removed');
    }
  }, []);

  const tryNativePlayback = useCallback(async () => {
    if (!streamUrl || !videoRef.current) return false;

    // Native <video src> is only valid for MP4 files, or for HLS on MSE-less
    // browsers. With MSE present, hls.js is the engine — refuse and un-stick
    // native mode so the next init returns to the hls.js path.
    if (!streamUrl.includes('.mp4') && (MSE_SUPPORTED || !supportsNativeHLS)) {
      console.warn('[@component:HLSVideoPlayer] Refusing native HLS fallback — hls.js is the supported engine here');
      setUseNativePlayer(false);
      return false;
    }

    console.log('[@component:HLSVideoPlayer] Trying native HTML5 playback');
    setUseNativePlayer(true);

    try {
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }

      // Clean up previous native playback handlers if any
      cleanupNativePlayback();

      const video = videoRef.current;

      const handleLoadedMetadata = () => {
        console.log('[@component:HLSVideoPlayer] Native playback loaded successfully');
        loadedStreamUrlRef.current = streamUrl;
        setStreamLoaded(true);
        setStreamError(null); // Clear any existing errors
        setRetryCount(0);
        onPlayerReady?.(); // Notify parent that player is ready
        attemptPlay();
      };

      const handleError = (e: any) => {
        const target = e.target as HTMLVideoElement;
        const mediaError = target?.error;
        
        console.warn('[@component:HLSVideoPlayer] Native playback error:', {
          event: e,
          mediaError,
          code: mediaError?.code,
          message: mediaError?.message,
        });
        
        // Mark stream as failed
        loadedStreamUrlRef.current = null;
        setStreamLoaded(false);
        setStreamError('Stream playback error. Retrying...');
        // A native error on an MSE browser means native was the wrong turn —
        // clear the sticky flag so the retry re-enters the hls.js path instead
        // of looping native attempts forever.
        if (MSE_SUPPORTED) {
          setUseNativePlayer(false);
        }
        
        // Trigger retry mechanism only if stream is still active
        if (isStreamActive) {
          setTimeout(() => {
            setRetryCount((prev) => prev + 1);
          }, retryDelay);
        } else {
          console.log('[@component:HLSVideoPlayer] Skipping retry - stream is paused (isStreamActive=false)');
        }
      };

      const handleCanPlay = () => {
        loadedStreamUrlRef.current = streamUrl;
        setStreamLoaded(true);
        setStreamError(null); // Clear any existing errors
        onPlayerReady?.(); // Notify parent that player is ready
      };

      // Store handlers for cleanup
      nativePlaybackHandlersRef.current = {
        loadedmetadata: handleLoadedMetadata,
        error: handleError,
        canplay: handleCanPlay,
      };

      video.addEventListener('loadedmetadata', handleLoadedMetadata);
      video.addEventListener('error', handleError);
      video.addEventListener('canplay', handleCanPlay);

      video.src = streamUrl + (streamUrl.includes('?') ? '&' : '?') + 't=' + Date.now();
      video.load();

      return true;
    } catch (error) {
      console.error('[@component:HLSVideoPlayer] Native playback setup failed:', error);
      return false;
    }
  }, [streamUrl, attemptPlay, cleanupNativePlayback, supportsNativeHLS, isStreamActive, retryDelay]);

  const initializeStream = useCallback(async () => {
    // Skip if stream is intentionally paused (e.g., modal closed, background player paused)
    if (!isStreamActive) {
      console.log('[@component:HLSVideoPlayer] Skipping init - stream is paused (isStreamActive=false)');
      return;
    }

    // Don't initialize if FFmpeg is stuck - requires external intervention
    if (ffmpegStuck) {
      console.warn('[@component:HLSVideoPlayer] FFmpeg is stuck, refusing to initialize stream');
      return;
    }

    // Reject re-entrant calls while an init is already running its async setup.
    // The init sets streamLoaded=false then awaits the hls.js import; during that yield
    // the "stream activated while not loaded" effect would otherwise fire another init,
    // causing the cleanup/reinit reload loop.
    if (initInFlightRef.current) {
      console.log('[@component:HLSVideoPlayer] Init already in flight, skipping re-entrant call');
      return;
    }

    // Already loaded this exact URL — nothing to do. Ref-based (not state) so a
    // stale-closure caller can't bypass it. Checked BEFORE the throttle and before
    // setStreamLoaded(false) below: without this, a redundant call (e.g. MP4/native
    // playback re-triggered by the activation effect) flips streamLoaded to false,
    // which re-arms the activation effect and spins an endless re-init loop.
    if (streamLoadedRef.current && loadedStreamUrlRef.current === streamUrl) {
      console.log('[@component:HLSVideoPlayer] Already loaded this URL, skipping initialization');
      return;
    }

    const now = Date.now();
    const elapsed = now - lastInitTime.current;
    if (elapsed < 1000) {
      // Reschedule instead of dropping — the caller (e.g. the URL-changed effect)
      // has already advanced its ref and marked streamLoaded=false, so a silent
      // drop here strands the player. Dedupe so a burst schedules only one retry.
      if (!pendingInitTimer.current) {
        console.log(
          '[@component:HLSVideoPlayer] Throttling initialization, scheduling retry',
        );
        pendingInitTimer.current = setTimeout(() => {
          pendingInitTimer.current = null;
          initializeStream();
        }, 1000 - elapsed + 50);
      } else {
        console.log(
          '[@component:HLSVideoPlayer] Throttling initialization, retry already scheduled',
        );
      }
      return;
    }
    // A real init is proceeding — drop any pending throttle retry, it's redundant now.
    if (pendingInitTimer.current) {
      clearTimeout(pendingInitTimer.current);
      pendingInitTimer.current = null;
    }
    lastInitTime.current = now;

    if (!streamUrl || !videoRef.current) {
      setStreamError('Stream URL or video element not available');
      return;
    }

    setStreamError(null);
    setStreamLoaded(false);
    setRequiresUserInteraction(false);
    setSegmentFailureCount(0);
    setFfmpegStuck(false);

    // Check if this is an MP4 file (recorded video)
    if (streamUrl.includes('.mp4')) {
      console.log('[@component:HLSVideoPlayer] Detected MP4 file, using native playback');
      const nativeSuccess = await tryNativePlayback();
      if (nativeSuccess) return;
    }

    if (!MSE_SUPPORTED && (useNativePlayer || (retryCount >= 2 && supportsNativeHLS))) {
      const nativeSuccess = await tryNativePlayback();
      if (nativeSuccess) return;
    }

    try {
      // Mark init in-flight for the whole async setup window (covers the dynamic import
      // yield where re-entrant inits would otherwise sneak in). Cleared in finally.
      initInFlightRef.current = true;
      console.log('[@component:HLSVideoPlayer] Initializing HLS stream:', streamUrl);

      // If HLS instance exists and URL changed, just reload source (safer than destroy/recreate)
      if (hlsRef.current && currentStreamUrl !== streamUrl) {
        console.log('[@component:HLSVideoPlayer] Reloading source without destroying HLS instance');
        console.log('[@component:HLSVideoPlayer] Old URL:', currentStreamUrl);
        console.log('[@component:HLSVideoPlayer] New URL:', streamUrl);
        setCurrentStreamUrl(streamUrl);
        setStreamLoaded(false); // Mark as not loaded during transition
        hlsRef.current.stopLoad();
        hlsRef.current.detachMedia();
        hlsRef.current.loadSource(streamUrl);
        hlsRef.current.attachMedia(videoRef.current);
        // The existing MANIFEST_PARSED handler will fire and call onPlayerReady
        console.log('[@component:HLSVideoPlayer] Source reloaded, waiting for manifest parse...');
        return;
      }

      // Full cleanup only if no HLS instance yet
      if (hlsRef.current) {
        cleanupStream();
      }

      setCurrentStreamUrl(streamUrl);

      const HLSModule = await import('hls.js');
      const HLS = HLSModule.default;

      if (!HLS.isSupported()) {
        console.log('[@component:HLSVideoPlayer] HLS.js not supported, using native playback');
        await tryNativePlayback();
        return;
      }

      // Dynamic HLS configuration based on mode
      const hlsConfig = isArchiveMode ? {
        // Archive mode - optimized for seeking and timeline navigation
        enableWorker: false,
        lowLatencyMode: false,         // Disable low latency for archive
        // Note: liveSyncDuration and liveMaxLatencyDuration omitted for archive mode
        // to avoid validation errors and let HLS.js use defaults
        maxBufferLength: 30,           // Larger buffer for smooth seeking
        maxMaxBufferLength: 60,        // Allow more buffering
        backBufferLength: 30,          // Keep back buffer for seeking
        maxBufferSize: 10 * 1000 * 1000, // Larger buffer size
        maxBufferHole: 2,              // More tolerance for gaps
        fragLoadingTimeOut: 10000,     // More time for fragment loading
        manifestLoadingTimeOut: 30000, // 30s timeout for large 24h manifests
        levelLoadingTimeOut: 30000,    // 30s timeout for large manifests
        liveBackBufferLength: 30,      // Keep back buffer
        liveDurationInfinity: false,   // Finite duration for archive
      } : {
        // Live mode - aggressive live edge with background buffering for 150s scrubbing.
        // The stream is plain 1s-segment HLS (server emits no LL-HLS parts), so the
        // floor is ~1.5-2s. The key to STAYING near it is maxLiveSyncPlaybackRate:
        // without it (default 1.0) hls.js can only correct drift by seeking once it
        // passes liveMaxLatencyDuration, so latency oscillates up to that cap (the old
        // ">4s"). With it, hls.js gently speeds up to glide back to the live edge.
        enableWorker: false,
        lowLatencyMode: true,          // ✅ Enable aggressive live edge targeting
        liveSyncDuration: 1.5,         // Target ~1.5s behind (one+ segment of safety; 1s stalled→drifted)
        liveMaxLatencyDuration: 4,     // Hard cap before seek-correct (was 5)
        maxLiveSyncPlaybackRate: 1.5,  // ✅ Smoothly speed up to catch live edge (1.0 = disabled = drift)
        maxBufferLength: 6,            // ✅ Load less ahead → start closer to live (was 10)
        maxMaxBufferLength: 150,       // But ALLOW up to 150s total as buffer fills
        backBufferLength: 150,         // Keep 150s for scrubbing (fills backward in background)
        maxBufferSize: 15 * 1000 * 1000, // 15MB for full 150s buffer
        maxBufferHole: 0.1,            // Fill gaps faster
        fragLoadingTimeOut: 5000,      // Fail faster
        manifestLoadingTimeOut: 3000,  // Fail faster
        levelLoadingTimeOut: 3000,     // Fail faster
        liveBackBufferLength: 150,     // ✅ Continue loading old segments backward (150s scrubbing)
        liveDurationInfinity: true,    // Allow infinite live duration
      };

      const hls = new HLS(
        streamIsGated
          ? {
              ...hlsConfig,
              // Applies to the manifest AND every segment hls.js derives from it.
              xhrSetup: (xhr: XMLHttpRequest) => {
                xhr.withCredentials = true;
              },
            }
          : hlsConfig,
      );

      hlsRef.current = hls;

      hls.on(HLS.Events.MANIFEST_PARSED, () => {
        console.log('[@component:HLSVideoPlayer] HLS manifest parsed successfully');
        loadedStreamUrlRef.current = streamUrl;
        setStreamLoaded(true);
        setStreamError(null); // Clear any existing errors
        setRetryCount(0);
        setSegmentFailureCount(0); // Reset segment failure count on successful manifest parse
        onPlayerReady?.(); // Notify parent that player is ready
        setFfmpegStuck(false); // Reset FFmpeg stuck state
        attemptPlay();
      });

      // Reset segment failure count on successful fragment loads
      hls.on(HLS.Events.FRAG_LOADED, (_event, data) => {
        setSegmentFailureCount(0);
        // Clear any existing error messages when fragments load successfully (indicates recovery)
        setStreamError((prev) => {
          if (prev) {
            console.log('[@component:HLSVideoPlayer] Stream recovered, clearing error message');
            return null;
          }
          return prev;
        });
        
        // Notify parent of current segment URL for screenshot/capture alignment
        if (data.frag?.url && onCurrentSegmentChange) {
          onCurrentSegmentChange(data.frag.url);
        }
      });

      // Latency correction removed - allow users to scrub back without auto-correction

      hls.on(HLS.Events.ERROR, (_event, data) => {
        // Ignore buffer-related errors and transient network timeouts - they are temporary and self-recovering
        if (data.details === 'bufferStalledError' ||
            data.details === 'bufferSeekOverHole' ||
            data.details === 'bufferNudgeOnStall' ||
            data.details === 'levelLoadTimeOut' ||
            data.details === 'fragLoadTimeOut') {
          // Silently ignore these - they are normal HLS.js recovery mechanisms
          return;
        }

        console.warn('[@component:HLSVideoPlayer] HLS error:', data.type, data.details, data.fatal, data);

        // Check for segment loading failures (404 errors indicating FFmpeg stuck)
        if (data.details === 'fragLoadError' && data.response?.code === 404) {
          setSegmentFailureCount((prev) => {
            // Don't increment if already at max - prevents counter from going beyond threshold
            if (prev >= maxSegmentFailures) {
              return prev;
            }
            
            const newCount = prev + 1;
            console.warn(`[@component:HLSVideoPlayer] Segment 404 error (${newCount}/${maxSegmentFailures}):`, data.frag?.url);
            
            if (newCount >= maxSegmentFailures) {
              console.error('[@component:HLSVideoPlayer] FFmpeg appears stuck - too many consecutive segment failures');
              setFfmpegStuck(true);
              setStreamError('FFmpeg appears stuck. Stream restart required.');
              
              // Immediately cleanup HLS instance to stop further attempts
              setTimeout(() => {
                if (hlsRef.current) {
                  try {
                    hlsRef.current.destroy();
                    hlsRef.current = null;
                  } catch (error) {
                    console.warn('[@component:HLSVideoPlayer] Error destroying HLS on FFmpeg stuck:', error);
                  }
                }
              }, 100);
              
              return newCount;
            }
            
            return newCount;
          });
          
          // Don't attempt recovery for segment failures - let them accumulate
          return;
        }

        // Reset segment failure count on successful operations or different error types
        if (data.details !== 'fragLoadError') {
          setSegmentFailureCount(0);
        }

        if (data.fatal) {
          console.error('[@component:HLSVideoPlayer] Fatal HLS error, trying recovery');

          // If stream is paused, never attempt fatal recovery (e.g. background preview while modal is open)
          if (!isStreamActive) {
            console.log('[@component:HLSVideoPlayer] Skipping fatal recovery - stream is paused (isStreamActive=false)');
            return;
          }

          // Special case: manifest 404 -> treat as terminal and stop retrying
          if (
            data.type === 'networkError' &&
            data.details === 'manifestLoadError' &&
            data.response?.code === 404
          ) {
            console.warn('[@component:HLSVideoPlayer] Manifest 404 - stopping retries and cleaning up');
            setStreamError('Stream manifest not found (404). Stream is unavailable.');
            // Clean up HLS instance to stop further requests
            cleanupStream();
            return;
          }

          // Fatal MEDIA errors (bufferAppendError on an audio/video SourceBuffer,
          // decode glitches after an ffmpeg restart changes the init segment, …)
          // have a designed in-place recovery in hls.js. Use it before tearing the
          // player down — a destructive restart blanks the card ("Loading stream…")
          // and makes a transient host-side hiccup look like a connection outage.
          if (data.type === 'mediaError') {
            const nowTs = Date.now();
            const rec = mediaRecoveryRef.current;
            try {
              if (nowTs - rec.lastAt > 10000) {
                rec.lastAt = nowTs;
                rec.swappedAudio = false;
                console.warn('[@component:HLSVideoPlayer] Fatal media error — recoverMediaError()');
                hls.recoverMediaError();
                return;
              }
              if (!rec.swappedAudio) {
                rec.lastAt = nowTs;
                rec.swappedAudio = true;
                console.warn('[@component:HLSVideoPlayer] Media error persists — swapAudioCodec() + recoverMediaError()');
                hls.swapAudioCodec();
                hls.recoverMediaError();
                return;
              }
            } catch (recErr) {
              console.warn('[@component:HLSVideoPlayer] recoverMediaError failed, falling back to restart', recErr);
            }
            // Third strike inside the window (or recover threw) — destructive restart below.
          }

          if (supportsNativeHLS && !MSE_SUPPORTED) {
            setUseNativePlayer(true);
            setTimeout(() => {
              // Only try native playback if stream is still active
              if (isStreamActive) {
                tryNativePlayback();
              } else {
                console.log('[@component:HLSVideoPlayer] Skipping native retry after fatal error - stream paused');
              }
            }, 500);
          } else {
            console.log('[@component:HLSVideoPlayer] Restarting HLS after fatal error');
            cleanupStream();
            setTimeout(() => {
              if (!isStreamActive) {
                console.log('[@component:HLSVideoPlayer] Skipping HLS restart after fatal error - stream paused');
                return;
              }
              setRetryCount(0);
              initializeStream();
            }, retryDelay);
          }
        } else {
          if (data.details === 'fragParsingError' || data.details === 'fragLoadError') {
            // Only attempt recovery if not stuck and not a 404 error
            if (!ffmpegStuck && !(data.details === 'fragLoadError' && data.response?.code === 404)) {
              console.log('[@component:HLSVideoPlayer] Fragment error, attempting HLS recovery');
              try {
                hls.startLoad();
              } catch (recoveryError) {
                console.warn('[@component:HLSVideoPlayer] HLS recovery failed:', recoveryError);
                setStreamError('Stream connection issues. Retrying...');
                setTimeout(() => {
                  setRetryCount((prev) => prev + 1);
                }, retryDelay);
              }
            }
          } else {
            setStreamError('Stream connection issues. Retrying...');
          }
        }
      });

      hls.loadSource(streamUrl);
      hls.attachMedia(videoRef.current);
    } catch (error: any) {
      console.error('[@component:HLSVideoPlayer] Stream initialization failed:', error);
      setStreamError(`Stream initialization failed: ${error.message}`);
      setTimeout(() => {
        setRetryCount((prev) => prev + 1);
      }, retryDelay);
    } finally {
      initInFlightRef.current = false;
    }
  }, [streamUrl, streamIsGated, retryCount, useNativePlayer, currentStreamUrl, cleanupStream, tryNativePlayback, ffmpegStuck, supportsNativeHLS, isStreamActive]);

  // Manual restart handler - clears all errors and reinitializes stream
  const handleManualRestart = useCallback(() => {
    console.log('[@component:HLSVideoPlayer] Manual restart triggered');
    // Reset all error states
    setStreamError(null);
    setSegmentFailureCount(0);
    setFfmpegStuck(false);
    setRetryCount(0);
    setStreamLoaded(false);
    setUseNativePlayer(false);
    
    // Cleanup current stream
    cleanupStream();
    
    // Reinitialize after cleanup
    setTimeout(() => {
      initializeStream();
    }, 300);
  }, [cleanupStream, initializeStream]);

  // Expose restart handler to parent via callback
  useEffect(() => {
    if (onRestartRequest) {
      // Store the restart handler so parent can call it
      (onRestartRequest as any).current = handleManualRestart;
    }
  }, [onRestartRequest, handleManualRestart]);

  const handleStreamError = useCallback(() => {
    // Don't retry if stream is paused
    if (!isStreamActive) {
      console.log('[@component:HLSVideoPlayer] Skipping retry - stream is paused (isStreamActive=false)');
      return;
    }

    // Don't retry if FFmpeg is stuck - requires external intervention
    if (ffmpegStuck) {
      console.warn('[@component:HLSVideoPlayer] FFmpeg stuck, not retrying - requires stream restart');
      return;
    }

    if (retryCount >= maxRetries) {
      if (supportsNativeHLS && !MSE_SUPPORTED) {
        console.warn('[@component:HLSVideoPlayer] Max retries reached, switching to native playback');
        setUseNativePlayer(true);
        setTimeout(() => tryNativePlayback(), 1000);
      } else {
        // Stay on hls.js: the watchdog hard-restart, visibility handler and the
        // Retry button all route back through handleManualRestart to recover.
        console.warn('[@component:HLSVideoPlayer] Max retries reached, awaiting restart (watchdog/visibility/manual)');
      }
      return;
    }

    console.log(
      `[@component:HLSVideoPlayer] Stream error, retrying in ${retryDelay}ms (attempt ${retryCount + 1}/${maxRetries})`,
    );

    setTimeout(() => {
      setRetryCount((prev) => {
        const newCount = prev + 1;
        console.log(`[@component:HLSVideoPlayer] Incrementing retry count: ${prev} -> ${newCount}`);
        return newCount;
      });
      initializeStream();
    }, retryDelay);
  }, [retryCount, maxRetries, retryDelay, initializeStream, tryNativePlayback, ffmpegStuck, isStreamActive]);

  useEffect(() => {
    // Don't retry if FFmpeg is stuck or stream is paused
    if (streamError && retryCount < maxRetries && !ffmpegStuck && isStreamActive) {
      console.log(
        `[@component:HLSVideoPlayer] Stream error detected, current retry count: ${retryCount}/${maxRetries}`,
      );
      // Only auto-retry if stream is not loaded (avoid retrying transient errors on working stream)
      if (!streamLoaded) {
        handleStreamError();
      }
    } else if (streamError && (retryCount >= maxRetries || ffmpegStuck)) {
      console.warn(
        `[@component:HLSVideoPlayer] ${ffmpegStuck ? 'FFmpeg stuck' : `Max retries (${maxRetries}) reached`}, stopping retry attempts`,
      );
    } else if (streamError && !isStreamActive) {
      console.log('[@component:HLSVideoPlayer] Stream error exists but stream is paused - not retrying');
    }
  }, [streamError, retryCount, maxRetries, streamLoaded, ffmpegStuck, isStreamActive, handleStreamError]);

  useEffect(() => {
    if (useNativePlayer && streamUrl && isStreamActive) {
      tryNativePlayback();
    }
  }, [useNativePlayer, streamUrl, isStreamActive, tryNativePlayback]);

  // Initialization - only on streamUrl change
  // Use refs to track current URL to avoid circular dependencies
  const currentStreamUrlRef = useRef<string | null>(null);
  
  useEffect(() => {
    if (!streamUrl || !videoRef.current) return;

    // Don't initialize during quality switching - wait for polling to complete
    if (shouldPause) {
      console.log('[@component:HLSVideoPlayer] Skipping init - quality switch in progress (shouldPause=true)');
      return;
    }

    // Only initialize if URL actually changed
    if (currentStreamUrlRef.current === streamUrl) {
      console.log('[@component:HLSVideoPlayer] Skipping init - same URL, already initialized');
      return;
    }

    console.log('[@component:HLSVideoPlayer] URL changed - initializing:', streamUrl);
    // Reset error states but don't cleanup (preserve if possible)
    setStreamError(null);
    setRetryCount(0);
    setSegmentFailureCount(0);
    setFfmpegStuck(false);
    setStreamLoaded(false);
    setCurrentStreamUrl(streamUrl);
    currentStreamUrlRef.current = streamUrl;

    initializeStream(); // Initialize without destructive cleanup
  }, [streamUrl, shouldPause, initializeStream]); // Depend on external props and the init callback

  // Initialize when the stream becomes active after mounting paused — e.g. the
  // player is rendered inside a collapsed/hidden container (MUI <Collapse> mounts
  // children eagerly with isStreamActive=false). The URL-changed effect above
  // only fires once per URL and skips while paused, and the pause/resume effect
  // needs an already-loaded stream, so without this a player first mounted with
  // isStreamActive=false would stay stuck on "Loading stream..." forever.
  useEffect(() => {
    if (!isStreamActive || !streamUrl || !videoRef.current) return;
    if (shouldPause || ffmpegStuck) return;
    if (streamLoaded || hlsRef.current) return;
    console.log('[@component:HLSVideoPlayer] Stream activated while not loaded - initializing');
    initializeStream();
  }, [isStreamActive, streamUrl, shouldPause, ffmpegStuck, streamLoaded, initializeStream]);

  // Handle shouldPause prop - pause to show last frame (e.g., during quality transition)
  const prevShouldPause = useRef(shouldPause);
  useEffect(() => {
    if (!videoRef.current) return;

    const shouldPauseChanged = prevShouldPause.current !== shouldPause;
    prevShouldPause.current = shouldPause;

    if (shouldPause) {
      console.log('[@component:HLSVideoPlayer] Quality switch started - pausing and preventing init');
      if (streamLoaded) {
        videoRef.current.pause();
      }
    } else if (shouldPauseChanged && streamUrl && isStreamActive) {
      // Only reinitialize when shouldPause changes from true to false (quality switch completes)
      console.log('[@component:HLSVideoPlayer] Quality switch complete (shouldPause changed from true to false) - initializing stream');
      setStreamLoaded(false);
      setStreamError(null);
      initializeStream();
    }
  }, [shouldPause, streamUrl, isStreamActive, streamLoaded, initializeStream]);

  // Pause/resume - non-destructive
  useEffect(() => {
    if (!hlsRef.current || !videoRef.current || !streamLoaded) return;

    if (isStreamActive) {
      console.log('[@component:HLSVideoPlayer] Resuming stream (non-destructive)');
      hlsRef.current.startLoad();
      attemptPlay();
    } else {
      console.log('[@component:HLSVideoPlayer] Pausing stream (non-destructive)');
      hlsRef.current.stopLoad();
      videoRef.current.pause();
    }
  }, [isStreamActive, streamLoaded, attemptPlay]);

  // Simplified video ready check - no polling needed
  useEffect(() => {
    const ready = !!videoRef.current;
    if (ready !== isVideoReady) {
      setIsVideoReady(ready);
      console.log('[@component:HLSVideoPlayer] Video ready state changed:', ready);
    }
  }, [streamLoaded, isVideoReady]);

  // Dedicated cleanup effect for component unmount - always runs
  useEffect(() => {
    return () => {
      console.log('[@component:HLSVideoPlayer] Final unmount cleanup');
      if (pendingInitTimer.current) {
        clearTimeout(pendingInitTimer.current);
        pendingInitTimer.current = null;
      }
      cleanupStream();
    };
  }, []); // Empty dependency array - only runs on mount/unmount

  // Add visibility change handler for recovery
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.hidden) {
        return;
      }

      console.log('[@component:HLSVideoPlayer] Tab became visible');
      if (!streamUrl || !isStreamActive) return;

      if (streamError || !streamLoaded || ffmpegStuck) {
        console.log('[@component:HLSVideoPlayer] Restarting stream on visibility change');
        handleManualRestart();
        return;
      }

      if (videoRef.current?.paused) {
        attemptPlay();
      }

      // Latency correction removed - allow users to stay at their chosen position
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [streamUrl, isStreamActive, streamError, streamLoaded, ffmpegStuck, handleManualRestart, attemptPlay, isArchiveMode]);

  // Stall watchdog — polls every 2s. Recovery escalates:
  //   1. Paused/stalled → soft resume (hls.startLoad + play), keeps streamLoaded=true
  //      so the "Loading stream..." overlay never appears for idle recovery.
  //   2. Still stalled after ~20s of soft attempts → fall back to destructive restart.
  // Skips archive mode where user-initiated pauses are legitimate.
  useEffect(() => {
    if (isArchiveMode) return;
    if (!streamUrl || !isStreamActive || !streamLoaded) return;
    if (shouldPause || streamError || ffmpegStuck || requiresUserInteraction) return;

    let lastAdvanceAt = Date.now();
    let lastCheckedTime = videoRef.current?.currentTime ?? 0;
    let softRecoveryAt: number | null = null;
    const hardRestartMs = 20000;

    const softResume = () => {
      try {
        hlsRef.current?.startLoad();
      } catch (err) {
        console.warn('[@component:HLSVideoPlayer] Watchdog: hls.startLoad failed', err);
      }
      attemptPlay();
      if (softRecoveryAt === null) softRecoveryAt = Date.now();
    };

    const interval = setInterval(() => {
      const video = videoRef.current;
      if (!video || document.hidden) return;

      const now = video.currentTime;

      if (now > lastCheckedTime) {
        lastCheckedTime = now;
        lastAdvanceAt = Date.now();
        softRecoveryAt = null;
        return;
      }

      if (video.paused && !video.ended) {
        console.log('[@component:HLSVideoPlayer] Watchdog: video paused, soft-resuming');
        softResume();
        return;
      }

      // readyState < HAVE_FUTURE_DATA (3) means the browser has nothing to play next.
      const starved = video.readyState < 3;
      if (!starved) return;

      const stalledFor = Date.now() - lastAdvanceAt;
      const soakingFor = softRecoveryAt !== null ? Date.now() - softRecoveryAt : 0;

      if (stalledFor >= hardRestartMs && soakingFor >= hardRestartMs) {
        console.log(
          `[@component:HLSVideoPlayer] Watchdog: soft resume failed for ${soakingFor}ms, hard restart`,
        );
        handleManualRestart();
        return;
      }

      console.log(
        `[@component:HLSVideoPlayer] Watchdog: starved ${stalledFor}ms (readyState=${video.readyState}), soft-resuming`,
      );
      softResume();
    }, 2000);

    return () => clearInterval(interval);
  }, [
    streamUrl,
    isStreamActive,
    streamLoaded,
    shouldPause,
    streamError,
    ffmpegStuck,
    requiresUserInteraction,
    isArchiveMode,
    attemptPlay,
    handleManualRestart,
  ]);

  return (
    <Box
      sx={{
        position: 'relative',
        width: '100%',
        height: '100%',
        backgroundColor: '#000000',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
        ...sx,
      }}
    >
            <video
        ref={videoRef}
        style={{
          width: '100%',
          height: '100%',
          maxWidth: '100%',
          objectFit: layoutConfig?.objectFit || 'contain',
          backgroundColor: '#000000',
          // Hide video during quality switch to prevent corrupted frames from showing
          display: streamLoaded && !shouldPause ? 'block' : 'none',
        }}
        autoPlay
        playsInline
        muted={muted}
        draggable={false}
        preload="none"
        crossOrigin={streamIsGated ? 'use-credentials' : 'anonymous'}
      />

      {visibleError && (
        <Box
          sx={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            textAlign: 'center',
            color: 'white',
            backgroundColor: 'rgba(0, 0, 0, 0.7)',
            padding: 2,
            borderRadius: 1,
            zIndex: 10,
          }}
        >
          <Typography variant="body2" sx={{ mb: 1 }}>
            {visibleError}
          </Typography>
          {ffmpegStuck ? (
            <Typography variant="caption" color="error.main">
              Segment failures: {segmentFailureCount}/{maxSegmentFailures}
            </Typography>
          ) : (
            <Typography variant="caption" color="text.secondary">
              Retry {retryCount}/{maxRetries}
            </Typography>
          )}
        </Box>
      )}

      {!streamLoaded && !visibleError && streamUrl && isStreamActive && (
        <Box
          sx={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            textAlign: 'center',
            color: 'white',
            zIndex: 10,
          }}
        >
          <Typography variant="body2">Loading stream...</Typography>
        </Box>
      )}

      {requiresUserInteraction && (
        <Box
          sx={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            textAlign: 'center',
            color: 'white',
            zIndex: 20,
          }}
        >
          <IconButton
            onClick={handleUserPlay}
            sx={{
              backgroundColor: 'rgba(0, 0, 0, 0.7)',
              color: 'white',
              '&:hover': {
                backgroundColor: 'rgba(0, 0, 0, 0.8)',
              },
            }}
            size="large"
          >
            <PlayArrowIcon fontSize="large" />
          </IconButton>
          <Typography variant="body2" sx={{ mt: 1 }}>
            Click to play
          </Typography>
        </Box>
      )}
    </Box>
  );
}

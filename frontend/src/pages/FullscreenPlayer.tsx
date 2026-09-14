import { Box, Typography } from '@mui/material';
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * FullscreenPlayer — dedicated "watch in best quality" page (opens in its own tab).
 *
 * Deliberately the OPPOSITE of the in-modal live player: it abandons the live edge
 * and builds a deep buffer so the HD stream never hitches. The in-modal player
 * (HLSVideoPlayer live config) pins playback to ~1.5s behind live with a tiny
 * buffer, which starves and stalls on any jitter. Here we sit ~12s behind live and
 * keep 30s buffered — latency is irrelevant for passive viewing.
 *
 * Self-contained on purpose: no archive/transcript/monitoring overlays, no
 * edge-seeking. It just plays whatever quality the device is currently encoding
 * (quality is a device-global, server-side setting; switch it from the modal).
 *
 * Query params:
 *   src   — encoded HLS manifest URL (live output.m3u8). Same-origin relative
 *           proxy paths (/host/<name>/stream/...) resolve fine in the new tab.
 *   name  — device/host label for the document title + overlay.
 *   muted — "1" to start muted (default unmuted; this is a deliberate watch view).
 */
export default function FullscreenPlayer() {
  const [searchParams] = useSearchParams();
  const src = searchParams.get('src');
  const name = searchParams.get('name') || 'Stream';
  const startMuted = searchParams.get('muted') === '1';

  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    document.title = `${name} — Fullscreen`;
  }, [name]);

  useEffect(() => {
    if (!src || !videoRef.current) return;
    const video = videoRef.current;
    let cancelled = false;

    // Quality-focused HLS config: deep buffer, no live-edge chasing.
    // Start well behind live and tolerate a lot of latency so the player rides on
    // a large cushion instead of the live edge — that's what prevents the hitching.
    const hlsConfig = {
      enableWorker: true,
      lowLatencyMode: false, // ✅ quality over latency — don't chase the edge
      liveSyncDuration: 18, // start ~18s behind live for a deep cushion
      liveMaxLatencyDuration: 50, // don't seek-correct until very far behind (keeps the cushion)
      maxLiveSyncPlaybackRate: 1, // never speed up to catch live (1 = disabled)
      maxBufferLength: 60, // load up to 60s ahead
      maxMaxBufferLength: 120, // allow up to 120s buffered
      backBufferLength: 30, // keep 30s behind
      maxBufferSize: 100 * 1000 * 1000, // 100MB — HD segments are bigger
      maxBufferHole: 0.5,
      nudgeMaxRetry: 10, // try harder to nudge past tiny gaps before giving up
      fragLoadingTimeOut: 20000,
      manifestLoadingTimeOut: 10000,
      liveDurationInfinity: true,
    };

    const setup = async () => {
      const HLSModule = await import('hls.js');
      const HLS = HLSModule.default;
      if (cancelled) return;

      // Safari / native HLS path
      if (!HLS.isSupported()) {
        if (video.canPlayType('application/vnd.apple.mpegurl')) {
          video.src = src;
          video.addEventListener('loadeddata', () => setLoaded(true), { once: true });
          video.addEventListener('error', () => setError('Stream playback error'), { once: true });
          return;
        }
        setError('HLS is not supported in this browser');
        return;
      }

      const hls = new HLS(hlsConfig);
      hlsRef.current = hls;

      hls.on(HLS.Events.MANIFEST_PARSED, () => {
        setLoaded(true);
        setError(null);
        video.play().catch(() => {
          /* autoplay may be blocked until first interaction; native controls cover it */
        });
      });

      hls.on(HLS.Events.ERROR, (_evt: any, data: any) => {
        if (!data.fatal) return;
        if (data.type === HLS.ErrorTypes.NETWORK_ERROR) {
          hls.startLoad();
        } else if (data.type === HLS.ErrorTypes.MEDIA_ERROR) {
          hls.recoverMediaError();
        } else {
          setError('Stream error — try reloading the tab');
          hls.destroy();
          hlsRef.current = null;
        }
      });

      hls.loadSource(src);
      hls.attachMedia(video);
    };

    setup();

    return () => {
      cancelled = true;
      if (hlsRef.current) {
        try {
          hlsRef.current.destroy();
        } catch {
          /* ignore */
        }
        hlsRef.current = null;
      }
    };
  }, [src]);

  if (!src) {
    return (
      <Box
        sx={{
          width: '100vw',
          height: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: 'black',
          color: 'white',
        }}
      >
        <Typography>No stream URL provided</Typography>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        position: 'fixed',
        inset: 0,
        width: '100vw',
        height: '100vh',
        backgroundColor: 'black',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {/* Live-only page: hide the native scrubber + time readout, keep play/volume/fullscreen.
          WebKit-only pseudo-elements (Chrome/Safari); harmless no-op elsewhere. */}
      <style>{`
        .fs-player-video::-webkit-media-controls-timeline,
        .fs-player-video::-webkit-media-controls-current-time-display,
        .fs-player-video::-webkit-media-controls-time-remaining-display {
          display: none !important;
        }
      `}</style>
      <video
        ref={videoRef}
        className="fs-player-video"
        style={{ width: '100%', height: '100%', objectFit: 'contain', backgroundColor: 'black' }}
        controls
        autoPlay
        playsInline
        muted={startMuted}
        crossOrigin="anonymous"
      />

      {/* Label */}
      <Typography
        variant="body2"
        sx={{
          position: 'absolute',
          top: 12,
          left: 16,
          color: 'white',
          backgroundColor: 'rgba(0,0,0,0.5)',
          px: 1,
          py: 0.25,
          borderRadius: 1,
          pointerEvents: 'none',
        }}
      >
        {name}
      </Typography>

      {!loaded && !error && (
        <Typography sx={{ position: 'absolute', color: 'white' }} variant="body2">
          Loading stream…
        </Typography>
      )}

      {error && (
        <Typography
          sx={{
            position: 'absolute',
            color: 'white',
            backgroundColor: 'rgba(0,0,0,0.7)',
            px: 2,
            py: 1,
            borderRadius: 1,
          }}
          variant="body2"
        >
          {error}
        </Typography>
      )}
    </Box>
  );
}

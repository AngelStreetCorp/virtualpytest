import { Box, Typography } from '@mui/material';
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

interface LatencyDebugState {
  /** Wall-clock seconds between now and the wall-clock on the last segment the player decoded. */
  wallSeconds: number;
  /** hls.js' own estimate (live edge - playback position). May be null before the first level loads. */
  hlsLatency: number | null;
  /** The target the player is steering toward (liveSyncDuration in live mode). */
  hlsTarget: number | null;
  /** True while the player's buffer is below maxBufferLength and waiting for data. */
  stalled: boolean;
}

const DEFAULT_STATE: LatencyDebugState = {
  wallSeconds: NaN,
  hlsLatency: null,
  hlsTarget: null,
  stalled: false,
};

/**
 * Debug overlay for the HLS player. Activated by `?latency_debug=1` in the URL
 * OR by an explicit `forceEnabled` prop. The latter lets a host modal show its
 * own toggle button (e.g. the rec header's "Latency" icon) so users don't have
 * to edit the URL — useful when the modal opens at a path that doesn't carry
 * the query param (TASK-79 phase-G follow-up).
 *
 * Displays the three numbers the TASK-79 spec asks for:
 *   - `Date.now() - hls.playingDate` — wall-clock seconds behind the live edge.
 *   - `hls.latency` — hls.js' own estimate of the same number.
 *   - `hls.targetLatency` — what the player is trying to sit at.
 *
 * The wall-clock is read off the EXT-X-PROGRAM-DATE-TIME tag written by the
 * encoder (`run_ffmpeg.sh` `program_date_time` hls_flag). Without that tag
 * hls.js has no anchor and `playingDate` is null — `wallSeconds` is then
 * NaN and the overlay shows "n/a". This is the intended signal that the
 * encoder is missing the flag.
 *
 * Stalls: the rAF loop flips `stalled` true on every `waiting` event and
 * false on every `playing` event. The overlay shows a one-line "stalls/min"
 * counter so a single page-load can show the rate the spec asks for.
 */
export const useLatencyDebug = (
  hlsRef: React.MutableRefObject<any>,
  forceEnabled?: boolean,
) => {
  const [searchParams] = useSearchParams();
  const urlEnabled = searchParams.get('latency_debug') === '1';
  const enabled = urlEnabled || forceEnabled === true;
  const [state, setState] = useState<LatencyDebugState>(DEFAULT_STATE);
  const [stallCount, setStallCount] = useState(0);
  const [elapsedSec, setElapsedSec] = useState(0);
  // Keep the live video element ref in a ref-of-ref so the rAF loop reads the
  // current one without re-creating the loop on every state update.
  const videoElRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    if (!enabled) return undefined;
    setState(DEFAULT_STATE);
    setStallCount(0);
    setElapsedSec(0);

    let raf = 0;
    let running = true;
    const startMs = performance.now();

    const tick = () => {
      if (!running) return;
      const now = Date.now();
      setElapsedSec((performance.now() - startMs) / 1000);

      const hls = hlsRef.current;
      const video = videoElRef.current;
      let wall = NaN;
      // hls.js exposes `playingDate` (Date | null) once the player has decoded
      // a segment that carried EXT-X-PROGRAM-DATE-TIME.
      if (hls && hls.playingDate) {
        wall = (now - hls.playingDate.getTime()) / 1000;
      }
      setState({
        wallSeconds: wall,
        hlsLatency: hls ? hls.latency ?? null : null,
        hlsTarget: hls ? hls.targetLatency ?? null : null,
        stalled: !!(video && video.readyState < 3 && !video.paused),
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    return () => {
      running = false;
      cancelAnimationFrame(raf);
    };
  }, [enabled, hlsRef]);

  // Wire the <video> element once HLSVideoPlayer has it. The HLSVideoPlayer
  // owns the ref; this hook is a sibling consumer.
  useEffect(() => {
    if (!enabled) return undefined;
    const root = document.querySelector('video');
    videoElRef.current = root;
    if (!root) return undefined;
    const onWaiting = () => setStallCount((c) => c + 1);
    root.addEventListener('waiting', onWaiting);
    return () => {
      root.removeEventListener('waiting', onWaiting);
      videoElRef.current = null;
    };
  }, [enabled]);

  const overlay = enabled
    ? (
        <Box
          data-testid="latency-debug-overlay"
          sx={{
            position: 'absolute',
            top: 8,
            right: 8,
            zIndex: 10,
            px: 1.25,
            py: 0.75,
            borderRadius: 1,
            backgroundColor: 'rgba(0,0,0,0.72)',
            color: 'primary.main',
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
            fontSize: 12,
            lineHeight: 1.35,
            pointerEvents: 'none',
            border: '1px solid',
            borderColor: 'primary.main',
          }}
        >
          <Typography component="div" sx={{ font: 'inherit', color: 'inherit' }}>
            wall:&nbsp;{Number.isFinite(state.wallSeconds) ? state.wallSeconds.toFixed(2) : 'n/a'}s
          </Typography>
          <Typography component="div" sx={{ font: 'inherit', color: 'inherit' }}>
            hls:&nbsp;{state.hlsLatency != null ? state.hlsLatency.toFixed(2) : 'n/a'}s
            &nbsp;target:&nbsp;{state.hlsTarget != null ? state.hlsTarget.toFixed(2) : 'n/a'}s
          </Typography>
          <Typography component="div" sx={{ font: 'inherit', color: 'inherit' }}>
            stalls:&nbsp;{stallCount}
            &nbsp;in&nbsp;{elapsedSec.toFixed(0)}s
            {state.stalled ? ' (buffering)' : ''}
          </Typography>
        </Box>
      )
    : null;

  return { enabled, overlay, state, stallCount, elapsedSec };
};

import { useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';

/**
 * Live playback metrics for the device stream, sampled straight off the <video>
 * element — NOT from the host. Every value here updates once a second, so it can be
 * read as "now" during a freeze investigation.
 *
 * Deliberately absent: capture-side (FPS in) and host ping RTT. Neither is measured
 * anywhere in the app — `video_fps` in `getAllHosts` is a static per-device capture
 * CAPABILITY, not a live reading, so surfacing it next to these live numbers would
 * imply a freshness it does not have.
 *
 * Null means "not measurable right now" (paused, no buffer, or the browser has no
 * playback-quality API). The overlay renders '—' for null rather than 0, because a
 * paused or unsupported player reporting "0 fps" reads as a broken stream.
 */
export interface LiveStreamStats {
  /** Decoded frames per second over the last sample window. */
  fps: number | null;
  /** Frames the browser dropped over the same window (decode pressure). */
  droppedFps: number | null;
  /** Seconds between the playhead and the end of the buffer. Live mode only. */
  latencySeconds: number | null;
}

const NO_STATS: LiveStreamStats = { fps: null, droppedFps: null, latencySeconds: null };

const SAMPLE_INTERVAL_MS = 1000;

/** Chrome/Safari/Edge expose getVideoPlaybackQuality; older Firefox only the webkit form. */
type VideoWithQuality = HTMLVideoElement & {
  webkitGetVideoPlaybackQuality?: () => { totalVideoFrames: number; droppedVideoFrames: number };
};

const readQuality = (video: HTMLVideoElement) => {
  const withQuality = video as VideoWithQuality;
  const read = video.getVideoPlaybackQuality ?? withQuality.webkitGetVideoPlaybackQuality;
  // Both `totalVideoFrames` and `droppedVideoFrames` are cumulative counters since load,
  // so the first sample has no baseline to diff against — reported as null, not 0.
  return typeof read === 'function' ? read.call(video) : null;
};

export const useLiveStreamStats = (
  videoRef: RefObject<HTMLVideoElement | null>,
  enabled: boolean,
  isLiveMode: boolean,
): LiveStreamStats => {
  const [stats, setStats] = useState<LiveStreamStats>(NO_STATS);
  const lastSampleRef = useRef<{ at: number; total: number; dropped: number } | null>(null);

  useEffect(() => {
    if (!enabled) {
      lastSampleRef.current = null;
      setStats(NO_STATS);
      return;
    }

    const tick = () => {
      const video = videoRef.current;
      if (!video || video.paused || video.readyState < 2) {
        // Paused or still loading: a frozen counter here would read as a stalled stream.
        lastSampleRef.current = null;
        setStats(NO_STATS);
        return;
      }

      const quality = readQuality(video);
      const now = performance.now();

      let latencySeconds: number | null = null;
      if (isLiveMode && video.buffered.length > 0) {
        latencySeconds = video.buffered.end(video.buffered.length - 1) - video.currentTime;
      }

      const previous = lastSampleRef.current;
      if (!quality || !previous) {
        lastSampleRef.current = quality
          ? { at: now, total: quality.totalVideoFrames, dropped: quality.droppedVideoFrames }
          : null;
        setStats({ fps: null, droppedFps: null, latencySeconds });
        return;
      }

      lastSampleRef.current = {
        at: now,
        total: quality.totalVideoFrames,
        dropped: quality.droppedVideoFrames,
      };

      // Background tabs throttle setInterval, so divide by the real elapsed time
      // instead of assuming the window was exactly SAMPLE_INTERVAL_MS.
      const elapsedSeconds = (now - previous.at) / 1000;
      if (elapsedSeconds <= 0) return;

      setStats({
        fps: Math.max(0, Math.round((quality.totalVideoFrames - previous.total) / elapsedSeconds)),
        droppedFps: Math.max(
          0,
          Math.round((quality.droppedVideoFrames - previous.dropped) / elapsedSeconds),
        ),
        latencySeconds,
      });
    };

    const intervalId = window.setInterval(tick, SAMPLE_INTERVAL_MS);
    // Prime the baseline immediately so the first painted sample is already a delta.
    tick();

    return () => window.clearInterval(intervalId);
  }, [videoRef, enabled, isLiveMode]);

  return stats;
};

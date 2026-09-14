import { useCallback, useEffect, useRef, useState } from 'react';

import {
  buildArchivedCaptureUrl,
  buildCaptureUrl,
  buildMetadataChunkUrl,
} from '../../../../frontend/src/utils/buildUrlUtils';
import type { ScreenVerdict } from '../../../../frontend/src/utils/screenVerdict';

/**
 * Per-frame detector data for one still (from the 10-min metadata chunk the
 * capture pipeline writes for 24h). Audio/subtitle are NOT archived per-frame
 * (only blackscreen/freeze/zapping survive) — for those, fall back to the
 * per-minute quality_metrics row (useAVQMetrics) in the consumer.
 */
export interface AVQFrameMeta {
  timestamp: string;
  blackscreen: boolean;
  blackscreen_percentage: number;
  freeze: boolean;
  freeze_diffs: number[];
  macroblocks?: boolean;
  audio?: boolean | null;
  volume_percentage?: number | null;
  mean_volume_db?: number | null;
  zapping_detected?: boolean;
  zapping_channel_name?: string;
  /** Per-frame Localize verdict (same shape the live overlay reads). null when disabled. */
  localize?: ScreenVerdict | null;
}

export interface AVQFrame {
  epochMs: number;
  /** archived-still filename number = seconds-of-day × 5 (5fps sequence space) */
  seq: number;
  imageUrl: string;
  /** true while the original hot frame is still on disk (last ~50s) */
  isLive: boolean;
  meta: AVQFrameMeta;
}

interface UseAVQFramesResult {
  /** 1fps frames for the 10-min window containing `targetEpochMs`, chronological. */
  frames: AVQFrame[];
  loading: boolean;
  /** Nearest frame to an arbitrary epoch within the loaded window (or null). */
  frameAt: (epochMs: number) => AVQFrame | null;
  refresh: () => void;
}

// The hot capture buffer holds ~60s; below this age the original still is on
// disk under its live filename, so we serve that instead of the cold archive.
const HOT_WINDOW_MS = 50_000;

const seqFromFilename = (filename?: string): string | null => {
  if (!filename) return null;
  const m = filename.match(/capture_(\d+)/);
  return m ? m[1] : null;
};

/**
 * Resolve 1fps full-res frames (+ per-frame metadata) for the AVQ frame inspector.
 * Chunk-driven: loads only the 10-min metadata chunk containing `targetEpochMs`
 * (cached), dedupes its 5fps frames to one-per-second, and picks each frame's
 * image URL by age (hot live file vs 24h cold archive). Stepping past the window
 * edges is handled by the consumer nudging `targetEpochMs` into the next window.
 */
export function useAVQFrames(
  host: any,
  deviceId: string | undefined,
  targetEpochMs: number | null,
): UseAVQFramesResult {
  const [frames, setFrames] = useState<AVQFrame[]>([]);
  const [loading, setLoading] = useState(false);
  const chunkCacheRef = useRef<Map<string, any>>(new Map());

  // Window key = (hour, 10-min chunk index) of the target time. Recomputed only
  // when the target crosses a chunk boundary, so panning within a window is free.
  const windowKey = (() => {
    if (targetEpochMs == null) return null;
    const d = new Date(targetEpochMs);
    const hour = d.getHours();
    const chunkIndex = Math.floor((d.getMinutes() * 60 + d.getSeconds()) / 600);
    return `${hour}_${chunkIndex}`;
  })();

  const build = useCallback(
    (chunkData: any): AVQFrame[] => {
      if (!deviceId || !chunkData?.frames || !Array.isArray(chunkData.frames)) return [];
      const now = Date.now();
      const bySecond = new Map<number, AVQFrame>();
      for (const f of chunkData.frames) {
        if (!f?.timestamp) continue;
        const epochMs = Date.parse(f.timestamp);
        if (Number.isNaN(epochMs)) continue;
        const d = new Date(epochMs);
        const secondsToday = d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds();
        if (bySecond.has(secondsToday)) continue; // 1fps: first frame of the second wins
        const seq = secondsToday * 5;
        const age = now - epochMs;
        let imageUrl: string;
        let isLive = false;
        const liveSeq = seqFromFilename(f.filename);
        if (age < HOT_WINDOW_MS && liveSeq) {
          imageUrl = buildCaptureUrl(host, liveSeq, deviceId);
          isLive = true;
        } else {
          imageUrl = buildArchivedCaptureUrl(host, deviceId, d.getHours(), seq);
        }
        bySecond.set(secondsToday, {
          epochMs,
          seq,
          imageUrl,
          isLive,
          meta: {
            timestamp: f.timestamp,
            blackscreen: f.blackscreen ?? false,
            blackscreen_percentage: f.blackscreen_percentage ?? 0,
            freeze: f.freeze ?? false,
            freeze_diffs: f.freeze_diffs || [],
            macroblocks: f.macroblocks ?? undefined,
            audio: f.audio ?? null,
            volume_percentage: f.volume_percentage ?? null,
            mean_volume_db: f.mean_volume_db ?? null,
            zapping_detected: f.zapping_detected ?? undefined,
            zapping_channel_name: f.zapping_channel_name ?? undefined,
            localize: f.localize ?? null,
          },
        });
      }
      return Array.from(bySecond.values()).sort((a, b) => a.epochMs - b.epochMs);
    },
    [host, deviceId],
  );

  const fetchWindow = useCallback(async () => {
    if (!deviceId || targetEpochMs == null) {
      setFrames([]);
      return;
    }
    const d = new Date(targetEpochMs);
    const hour = d.getHours();
    const chunkIndex = Math.floor((d.getMinutes() * 60 + d.getSeconds()) / 600);
    const cacheKey = `${deviceId}_${hour}_${chunkIndex}`;

    let chunkData = chunkCacheRef.current.get(cacheKey);
    if (!chunkData) {
      setLoading(true);
      try {
        // Fetch the metadata chunk directly from the host (same path useMonitoring uses).
        const url = buildMetadataChunkUrl(host, deviceId, hour, chunkIndex);
        const resp = await fetch(url);
        if (resp.ok) {
          chunkData = await resp.json();
          chunkCacheRef.current.set(cacheKey, chunkData);
        } else {
          setFrames([]);
          return;
        }
      } catch {
        setFrames([]);
        return;
      } finally {
        setLoading(false);
      }
    }
    setFrames(build(chunkData));
  }, [host, deviceId, targetEpochMs, build]);

  useEffect(() => {
    fetchWindow();
    // Re-run only when the window (or device) changes, not on every targetEpochMs tick.
  }, [deviceId, windowKey, host?.host_name]);

  const frameAt = useCallback(
    (epochMs: number): AVQFrame | null => {
      if (frames.length === 0) return null;
      let best = frames[0];
      let bestD = Infinity;
      for (const f of frames) {
        const dd = Math.abs(f.epochMs - epochMs);
        if (dd < bestD) {
          bestD = dd;
          best = f;
        }
      }
      return best;
    },
    [frames],
  );

  const refresh = useCallback(() => {
    chunkCacheRef.current.clear();
    fetchWindow();
  }, [fetchWindow]);

  return { frames, loading, frameAt, refresh };
}

import { useCallback, useEffect, useState } from 'react';

import { api } from '../../../../frontend/src/utils/apiClient';
import { buildServerUrl } from '../../../../frontend/src/utils/buildUrlUtils';

// Shared "is it actually present" thresholds for transcript/subtitle availability
// (fraction of frames in the minute). Used by BOTH the timeline presence lanes and
// the L2 accordions so they never disagree. Subtitles need >0.5 because OCR
// false-positives on on-screen graphics produce low-availability garbage.
export const TRANSCRIPT_PRESENT = 0.5;
export const SUBTITLE_PRESENT = 0.5;

// One RLE'd Localize "where was the device" span (epoch-ms). kind drives the
// Position-lane colour: confident=green, ambiguous=yellow, no_signal/blackscreen
// = named capture states, unknown=grey. node is null for state/unknown spans.
export type PositionKind =
  | 'confident'
  | 'ambiguous'
  | 'no_signal'
  | 'blackscreen'
  | 'unknown';
export interface TimelinePosition {
  s: number; // epoch ms start
  e: number; // epoch ms end
  node: string | null;
  kind: PositionKind;
  conf: number;
}

// One per-minute AVQ row (mirrors quality_metrics columns).
export interface AVQMetric {
  timestamp: string;
  // video
  blurriness_score: number | null;
  blockiness_score: number | null;
  jerkiness_score: number | null;
  clean_video_seconds: number | null;
  video_availability: number | null;
  video_mos: number | null;
  // incidents (from the realtime detector)
  blackscreen_seconds: number | null;
  freeze_seconds: number | null;
  macroblocks_seconds: number | null;
  // audio
  audio_level_db: number | null;
  loudness_lkfs: number | null;
  loudness_range: number | null;
  true_peak_dbtp: number | null;
  saturation_score: number | null;
  silence_seconds: number | null;
  audio_availability: number | null;
  audio_mos: number | null;
  // subtitles / transcription / translation (null when feature disabled)
  subtitle_availability: number | null;
  subtitle_language: string | null;
  subtitle_text: string | null;
  transcript_available: number | null;
  transcript_language: string | null;
  transcript_text: string | null;
  translation_languages: string | null;
  dubbed_languages: string | null;
  events: Record<
    string,
    { count: number; totalMs: number; perMinute?: number; avgMs?: number; longestMs?: number }
  > | null;
  // RLE'd Localize screen position over this minute (null when Localize disabled).
  positions: TimelinePosition[] | null;
}

interface UseAVQMetricsResult {
  metrics: AVQMetric[];
  latest: AVQMetric | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => void;
}

/**
 * Fetch per-minute AVQ metrics for a device over the last `hours` (default 24).
 * Polls every 60s while mounted.
 */
export function useAVQMetrics(
  deviceId: string | undefined,
  hostName?: string,
  hours = 24,
): UseAVQMetricsResult {
  const [metrics, setMetrics] = useState<AVQMetric[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchMetrics = useCallback(async () => {
    if (!deviceId) return;
    setIsLoading(true);
    setError(null);
    try {
      // host_name is required: device_id is not unique across hosts.
      const hostParam = hostName ? `&host_name=${encodeURIComponent(hostName)}` : '';
      const result = await api.get(
        buildServerUrl(`/server/monitoring/avq?device_id=${encodeURIComponent(deviceId)}${hostParam}&hours=${hours}`),
      );
      setMetrics(Array.isArray(result?.metrics) ? result.metrics : []);
    } catch (e: any) {
      setError(e?.message || 'Failed to load AVQ metrics');
    } finally {
      setIsLoading(false);
    }
  }, [deviceId, hostName, hours]);

  useEffect(() => {
    fetchMetrics();
    const id = setInterval(fetchMetrics, 60_000);
    return () => clearInterval(id);
  }, [fetchMetrics]);

  return {
    metrics,
    latest: metrics.length > 0 ? metrics[metrics.length - 1] : null,
    isLoading,
    error,
    refresh: fetchMetrics,
  };
}

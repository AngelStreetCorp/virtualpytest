import { useState, useEffect, useRef, useCallback } from 'react';

import { Host } from '../../../types/common/Host_Types';
import { buildTranscriptChunkUrl } from '../../../utils/buildUrlUtils';
import { TranscriptData10Min } from '../EnhancedHLSPlayer.types';

/**
 * One rendered line in the live transcript rail.
 * `id` is stable across polls so re-fetching the same chunk does not duplicate lines.
 */
export interface LiveTranscriptLine {
  id: string;
  timestamp: string; // wall-clock time-of-day, e.g. "20:14:31"
  text: string;
  source: 'audio';
}

interface UseLiveTranscriptFeedProps {
  isLiveMode: boolean;
  host?: Host;
  deviceId: string;
  enabled?: boolean;
}

// The accumulator transcribes one 1-minute MP3 at a time, so the chunk JSON only
// gains new segments about once a minute. Polling faster just burns requests.
const POLL_INTERVAL_MS = 15000;
// Keep the rail bounded; roughly the last ~40 minutes of dense speech.
const MAX_LINES = 200;

const CHUNK_MINUTES = 10;

/** Current transcript chunk (hour + index within the hour) from the wall clock. */
const getCurrentChunk = (): { hour: number; chunkIndex: number } => {
  const now = new Date();
  return {
    hour: now.getHours(),
    chunkIndex: Math.floor(now.getMinutes() / CHUNK_MINUTES),
  };
};

/** Local calendar date as YYYY-MM-DD (matches the host's naive isoformat prefix). */
const localDateStr = (): string => {
  const d = new Date();
  return [d.getFullYear(), d.getMonth() + 1, d.getDate()]
    .map((v, i) => String(v).padStart(i === 0 ? 4 : 2, '0'))
    .join('-');
};

/**
 * The chunk path is keyed by hour + chunkIndex only — no date — so before
 * today's audio for this 10-min window has been transcribed, the host still
 * serves YESTERDAY's file for the same slot, and its lines carry today-looking
 * time-of-day labels. The chunk's top-level `timestamp` is rewritten on every
 * merge (including the host's own day-rollover clear), so a chunk whose date
 * isn't today's is entirely stale. Assumes host and browser share a timezone
 * (both CET here); at worst this is off only in the minutes around midnight.
 */
const isStaleChunk = (data: TranscriptData10Min): boolean => {
  const ts = data?.timestamp;
  if (typeof ts !== 'string' || ts.length < 10) return false; // legacy: don't over-filter
  return ts.slice(0, 10) !== localDateStr();
};

/**
 * Segment `start` is relative to the chunk start, and the chunk starts at
 * hour:(chunkIndex*10). Turn that into a time-of-day label for the rail.
 */
const formatSegmentTime = (hour: number, chunkIndex: number, startSeconds: number): string => {
  const total = hour * 3600 + chunkIndex * CHUNK_MINUTES * 60 + Math.floor(startSeconds);
  const h = Math.floor(total / 3600) % 24;
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map((v) => String(v).padStart(2, '0')).join(':');
};

/**
 * Live transcript feed for the right rail.
 *
 * Reads the same per-10-min chunk JSON that `transcript_accumulator.py` writes
 * progressively (one minute at a time) on the host — no socket, no streaming tap.
 * That means lines land ~1 minute behind live, in minute-sized batches.
 *
 * Requires transcription to be enabled on the host (ENABLE_TRANSCRIPTION=true);
 * without it the chunk JSON never appears and the feed stays empty.
 */
export const useLiveTranscriptFeed = ({
  isLiveMode,
  host,
  deviceId,
  enabled = true,
}: UseLiveTranscriptFeedProps) => {
  const [lines, setLines] = useState<LiveTranscriptLine[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [hasTranscript, setHasTranscript] = useState(false);

  // Ids already rendered — dedupes across polls and across chunk rollover.
  const seenIdsRef = useRef<Set<string>>(new Set());

  // Text of the last line actually rendered, so consecutive identical lines
  // (e.g. a repeated on-screen subtitle) collapse to the first occurrence.
  const lastTextRef = useRef<string | null>(null);

  // VNC devices have no audio capture, so they never produce a transcript.
  const isVncDevice = host?.devices?.some(
    (d: any) => d?.device_id === deviceId && d?.device_model === 'host_vnc',
  );

  const active = isLiveMode && enabled && !!host && !!deviceId && !isVncDevice;

  const reset = useCallback(() => {
    seenIdsRef.current = new Set();
    lastTextRef.current = null;
    setLines([]);
    setHasTranscript(false);
  }, []);

  // Drop accumulated lines when the feed goes inactive or the device changes,
  // so switching device never shows another device's transcript.
  useEffect(() => {
    if (!active) reset();
  }, [active, deviceId, reset]);

  useEffect(() => {
    if (!active) return;

    let cancelled = false;

    const poll = async () => {
      const { hour, chunkIndex } = getCurrentChunk();
      const url = buildTranscriptChunkUrl(host, deviceId, hour, chunkIndex, 'original');

      try {
        setIsLoading(true);
        const res = await fetch(url);
        if (!res.ok) {
          // 404 is expected: the chunk file does not exist until the first
          // minute of it has been transcribed.
          return;
        }

        const data: TranscriptData10Min = await res.json();
        // Yesterday's file still served for this slot until today's audio is
        // transcribed — skip it wholesale rather than render last day's speech.
        if (isStaleChunk(data)) return;

        const segments = data.segments || [];
        if (cancelled || segments.length === 0) return;

        const fresh: LiveTranscriptLine[] = [];
        for (const seg of segments) {
          const text = (seg.text || '').trim();
          if (!text) continue;

          const id = `${hour}-${chunkIndex}-${seg.start}`;
          if (seenIdsRef.current.has(id)) continue;
          seenIdsRef.current.add(id);

          // Collapse consecutive identical lines to the first occurrence.
          if (text === lastTextRef.current) continue;
          lastTextRef.current = text;

          fresh.push({
            id,
            timestamp: formatSegmentTime(hour, chunkIndex, seg.start),
            text,
            source: 'audio',
          });
        }

        if (fresh.length > 0 && !cancelled) {
          setHasTranscript(true);
          setLines((prev) => [...prev, ...fresh].slice(-MAX_LINES));
        }
      } catch (err) {
        console.log(`[@useLiveTranscriptFeed] Poll failed for ${deviceId}:`, err);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };

    poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [active, host, deviceId]);

  return { lines, isLoading, hasTranscript };
};

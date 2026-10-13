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
  timestamp: string; // wall-clock time-of-day of the ORIGINAL segment, e.g. "20h14m31s"
  text: string;
  /** Text was rewritten by the host's LLM spelling/grammar pass after first display. */
  corrected: boolean;
  /** Whisper's original text, set when `corrected`. */
  rawText?: string;
  source: 'audio';
  /** Seconds since midnight of the segment start; keeps late lines in order. */
  sortKey: number;
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
// The last minute of a chunk is transcribed after the window rolls over, and the
// host's LLM correction lands later still, so the previous chunk keeps being polled
// for the first minutes of each window.
const PREVIOUS_CHUNK_TAIL_MINUTES = 3;

/** Current transcript chunk (hour + index within the hour) from the wall clock. */
const getCurrentChunk = (): { hour: number; chunkIndex: number } => {
  const now = new Date();
  return {
    hour: now.getHours(),
    chunkIndex: Math.floor(now.getMinutes() / CHUNK_MINUTES),
  };
};

/** Chunk before (hour, chunkIndex); null at midnight (yesterday's chunk is stale). */
const getPreviousChunk = (hour: number, chunkIndex: number): { hour: number; chunkIndex: number } | null => {
  if (chunkIndex > 0) return { hour, chunkIndex: chunkIndex - 1 };
  if (hour > 0) return { hour: hour - 1, chunkIndex: 60 / CHUNK_MINUTES - 1 };
  return null;
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
  const pad = (v: number) => String(v).padStart(2, '0');
  return `${pad(h)}h${pad(m)}m${pad(s)}s`;
};

/**
 * Live transcript feed for the right rail.
 *
 * Reads the same per-10-min chunk JSON that `transcript_accumulator.py` writes
 * progressively (one minute at a time) on the host — no socket, no streaming tap.
 * That means lines land ~1 minute behind live, in minute-sized batches.
 *
 * Requires transcription to be enabled on the host (ENABLE_TRANSCRIPTION=true);
 * without it the chunk JSON never appears. `isAvailable` turns true only once a
 * chunk written TODAY has been fetched, proof the service is on and transcribing.
 * Silent minutes are skipped (no merge), so on a quiet device the rail stays
 * hidden until the first speech lands. Callers hide the rail until then instead
 * of showing an empty "Waiting for speech…" forever.
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
  const [isAvailable, setIsAvailable] = useState(false);

  // Ids already rendered — dedupes across polls and across chunk rollover.
  const seenIdsRef = useRef<Set<string>>(new Set());

  // Raw text of the last line actually rendered, so consecutive identical lines
  // (e.g. a repeated on-screen subtitle) collapse to the first occurrence.
  // Compared on raw text so a later correction does not change what collapses.
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
    setIsAvailable(false);
  }, []);

  // Drop accumulated lines when the feed goes inactive or the device changes,
  // so switching device never shows another device's transcript.
  useEffect(() => {
    if (!active) reset();
  }, [active, deviceId, reset]);

  useEffect(() => {
    if (!active) return;

    let cancelled = false;
    let availableLatched = false;

    /** Fetch a chunk; null when missing (404) or left over from yesterday. */
    const fetchFreshChunk = async (
      hour: number,
      chunkIndex: number,
    ): Promise<TranscriptData10Min | null> => {
      const res = await fetch(buildTranscriptChunkUrl(host, deviceId, hour, chunkIndex, 'original'));
      if (!res.ok) return null;
      const data: TranscriptData10Min = await res.json();
      return isStaleChunk(data) ? null : data;
    };

    const markAvailable = () => {
      if (availableLatched || cancelled) return;
      availableLatched = true;
      setIsAvailable(true);
    };

    const poll = async () => {
      const current = getCurrentChunk();
      const previous = getPreviousChunk(current.hour, current.chunkIndex);
      const inTail = new Date().getMinutes() % CHUNK_MINUTES < PREVIOUS_CHUNK_TAIL_MINUTES;

      try {
        setIsLoading(true);
        // The previous chunk also proves the service runs while the current one is
        // still missing (it does not exist until its first minute is transcribed).
        const targets = previous && (inTail || !availableLatched) ? [previous, current] : [current];
        const chunks: { hour: number; chunkIndex: number; data: TranscriptData10Min }[] = [];
        for (const target of targets) {
          // null: 404, or yesterday's file still served for this slot — skip it
          // wholesale rather than render last day's speech.
          const data = await fetchFreshChunk(target.hour, target.chunkIndex);
          if (data) chunks.push({ ...target, data });
        }
        if (cancelled || chunks.length === 0) return;
        markAvailable();

        const fresh: LiveTranscriptLine[] = [];
        // Corrections for lines already rendered: the host rewrites `text` in place
        // (keeping `raw_text`) once its LLM pass lands, without changing `start`.
        const updates = new Map<string, string>();
        for (const { hour, chunkIndex, data } of chunks) {
          for (const seg of data.segments || []) {
            const text = (seg.text || '').trim();
            if (!text) continue;

            const id = `${hour}-${chunkIndex}-${seg.start}`;
            if (seenIdsRef.current.has(id)) {
              if (seg.raw_text) updates.set(id, text);
              continue;
            }
            seenIdsRef.current.add(id);

            const rawText = (seg.raw_text || text).trim();
            // Collapse consecutive identical lines to the first occurrence.
            if (rawText === lastTextRef.current) continue;
            lastTextRef.current = rawText;

            fresh.push({
              id,
              timestamp: formatSegmentTime(hour, chunkIndex, seg.start),
              text,
              corrected: !!seg.raw_text,
              rawText: seg.raw_text || undefined,
              source: 'audio',
              sortKey: hour * 3600 + chunkIndex * CHUNK_MINUTES * 60 + seg.start,
            });
          }
        }

        if (fresh.length > 0) setHasTranscript(true);
        if (fresh.length > 0 || updates.size > 0) {
          setLines((prev) => {
            const patched = updates.size
              ? prev.map((line) => {
                  const text = updates.get(line.id);
                  return text && text !== line.text
                    ? { ...line, text, corrected: true, rawText: line.rawText ?? line.text }
                    : line;
                })
              : prev;
            if (fresh.length === 0) return patched;
            return [...patched, ...fresh].sort((a, b) => a.sortKey - b.sortKey).slice(-MAX_LINES);
          });
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

  return { lines, isLoading, hasTranscript, isAvailable };
};

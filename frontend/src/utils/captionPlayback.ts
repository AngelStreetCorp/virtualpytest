/**
 * Caption playback (TASK-103): pure helpers for the delayed player. The player plays the device
 * `delay_s` behind live from the archive's growing 10-minute chunk, never past the last minute whose
 * transcript exists, and shows machine captions built from the chunk transcript.
 */

export const CAPTION_PROFILE = 'caption_playback';
export const DEFAULT_DELAY_S = 150;
export const CHUNK_SECONDS = 600;
export const CAPTION_LANG_STORAGE_KEY = 'virtualpytest:caption-language';

const LANGUAGE_CODES: Record<string, string> = { english: 'en', french: 'fr', german: 'de', spanish: 'es', italian: 'it' };
/** The host reports the spoken language as a name ("German"), the picker uses codes ("de"). */
export const languageCode = (language: string | null | undefined): string | null => {
  const l = (language ?? '').trim().toLowerCase();
  return l ? (LANGUAGE_CODES[l] ?? l) : null;
};

export interface CaptionMinute {
  minute: number;
  caption_source: 'machine' | 'broadcaster' | 'none';
  ready: boolean;
}
/** Response of GET /server/transcript/captions (TASK-103 §7.2). */
export interface CaptionsResponse {
  language: string | null;
  /** Spoken language when `language` is a translation. */
  source_language?: string | null;
  vtt: string;
  minutes: CaptionMinute[];
}
export interface ManifestChunk {
  hour: number;
  chunk_index: number;
  /** Epoch seconds the host wrote the chunk. */
  created: number;
  /** Host wall-clock end of the chunk, no timezone ("2026-10-15T12:49:59.230385"). */
  end_time?: string;
}
export interface PlaybackTarget {
  hour: number;
  chunkIndex: number;
  /** Seconds into the chunk file. */
  offset: number;
}

/**
 * The archive names its files by the HOST's clock hour, not the browser's. The offset of the host's wall clock
 * from UTC, read off the newest manifest chunk (its wall-clock `end_time` against its epoch `created`, rounded to
 * 15 min); null until the manifest says.
 */
export const hostOffsetMs = (chunks: ManifestChunk[]): number | null => {
  let newest: ManifestChunk | null = null;
  for (const c of chunks) if (c.end_time && (!newest || c.created > newest.created)) newest = c;
  if (!newest?.end_time) return null;
  const wall = Date.parse(`${newest.end_time.slice(0, 19)}Z`);
  if (Number.isNaN(wall)) return null;
  const q = 15 * 60_000;
  return Math.round((wall - newest.created * 1000) / q) * q;
};

/** The host's time of day, in seconds, at `nowMs` for a host `offsetMs` ahead of UTC. */
export const hostSecondOfDay = (nowMs: number, offsetMs: number): number => {
  const d = new Date(nowMs + offsetMs);
  return d.getUTCHours() * 3600 + d.getUTCMinutes() * 60 + d.getUTCSeconds();
};

/** Where `delay_s` behind `nowMs` lies, in the host-clock-hour/10-minute-chunk the archive names files by. */
export const targetPosition = (nowMs: number, delayS: number, offsetMs: number): PlaybackTarget => {
  const d = new Date(nowMs + offsetMs - delayS * 1000);
  const secOfHour = d.getUTCMinutes() * 60 + d.getUTCSeconds() + d.getUTCMilliseconds() / 1000;
  const chunkIndex = Math.floor(secOfHour / CHUNK_SECONDS);
  return { hour: d.getUTCHours(), chunkIndex, offset: secOfHour - chunkIndex * CHUNK_SECONDS };
};

/** The newest manifest entry for a target's hour/chunk (rolling 24 h archives reuse names: take the newest). */
export const findChunk = (chunks: ManifestChunk[], hour: number, chunkIndex: number): ManifestChunk | null => {
  let best: ManifestChunk | null = null;
  for (const c of chunks) {
    if (c.hour === hour && c.chunk_index === chunkIndex && (!best || c.created > best.created)) best = c;
  }
  return best;
};

/** Seconds of the chunk the player may play: the end of the last minute the host has processed. */
export const readyUntil = (minutes: CaptionMinute[] | undefined): number => {
  let last = -1;
  for (const m of minutes ?? []) if (m.ready && m.minute > last) last = m.minute;
  return (last + 1) * 60;
};

export const formatBehind = (seconds: number): string => {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

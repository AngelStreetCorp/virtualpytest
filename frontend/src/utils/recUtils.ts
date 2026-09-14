/**
 * Shared utilities for REC (recording/restart) components.
 */

const LANGUAGE_NAMES: Record<string, string> = {
  en: 'English',
  es: 'Spanish',
  fr: 'French',
  de: 'German',
  it: 'Italian',
  pt: 'Portuguese',
  ru: 'Russian',
  ja: 'Japanese',
  ko: 'Korean',
  zh: 'Chinese',
};

export const getLanguageName = (code: string): string =>
  LANGUAGE_NAMES[code.toLowerCase()] ?? code.toUpperCase();

/**
 * A running.log is considered stale (a leftover from a finished/dead run) once its
 * start_time is older than this. No legitimate single script/campaign run on these
 * devices lasts this long, so anything older is a never-cleaned-up log and must not
 * drive the "script running" overlay (which would otherwise show "finishing..." forever).
 */
const RUNNING_LOG_MAX_AGE_MS = 12 * 60 * 60 * 1000; // 12h

export const isRunningLogStale = (startTime: string | undefined): boolean => {
  if (!startTime) return false;
  const start = new Date(startTime).getTime();
  if (Number.isNaN(start)) return false;
  return Date.now() - start > RUNNING_LOG_MAX_AGE_MS;
};

/** Format remaining time until estimated end. */
export const getTimeRemaining = (estimatedEnd: string | undefined): string | null => {
  if (!estimatedEnd) return null;
  const now = Date.now();
  const end = new Date(estimatedEnd).getTime();
  const remainingMs = end - now;
  if (Number.isNaN(end)) return null;
  if (remainingMs <= 0) return 'finishing...';
  const minutes = Math.floor(remainingMs / 60000);
  const seconds = Math.floor((remainingMs % 60000) / 1000);
  return minutes > 0 ? `${minutes}m ${seconds}s left` : `${seconds}s left`;
};

/** Human-readable duration from seconds, e.g. 77391 → "21h 29m". */
export const formatDuration = (totalSeconds: number): string => {
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) return '–';
  const s = Math.floor(totalSeconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
};

/**
 * Start-time + live duration lines for a device lock tooltip, derived from the
 * lock's `locked_at` epoch (seconds). Duration is computed against now so it stays
 * current between lock refreshes — a multi-hour value flags a stale/zombie lock.
 * Returns null when the lock carries no usable timestamp.
 */
export const getLockTimingLines = (
  lockInfo: { locked_at?: number; lock_age_seconds?: number } | null | undefined,
): { startedAt: string; duration: string } | null => {
  if (!lockInfo) return null;
  const lockedAt = typeof lockInfo.locked_at === 'number' ? lockInfo.locked_at : null;
  if (!lockedAt) return null;
  const ageSeconds = Date.now() / 1000 - lockedAt;
  return {
    startedAt: new Date(lockedAt * 1000).toLocaleString(),
    duration: formatDuration(ageSeconds),
  };
};

/** Format YYYYMMDDHHMMSS timestamp into DD/MM/YYYY HH:mm:ss. */
export const formatCompactTimestamp = (timestamp: string): string => {
  if (!timestamp || timestamp.length !== 14) return timestamp;
  const year = timestamp.slice(0, 4);
  const month = timestamp.slice(4, 6);
  const day = timestamp.slice(6, 8);
  const hour = timestamp.slice(8, 10);
  const minute = timestamp.slice(10, 12);
  const second = timestamp.slice(12, 14);
  return `${day}/${month}/${year} ${hour}:${minute}:${second}`;
};

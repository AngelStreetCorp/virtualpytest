/**
 * Date and Time Utility Functions
 * 
 * Handles timezone-aware date formatting for the application.
 * All timestamps from the backend are expected to be in UTC ISO 8601 format.
 * These utilities convert them to the user's local timezone for display.
 */
import { getIntlLocale, translate as t, translatePlural as tn } from '../i18n';

/**
 * Get the user's timezone
 */
export const getUserTimezone = (): string => {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
};

/**
 * Format a UTC ISO timestamp to local time string
 * @param utcTimestamp - ISO 8601 timestamp string in UTC
 * @returns Formatted date string in local timezone
 */
export const formatToLocalTime = (utcTimestamp: string | null | undefined): string => {
  if (!utcTimestamp) return '-';
  
  try {
    const date = new Date(utcTimestamp);
    if (isNaN(date.getTime())) return utcTimestamp;
    
    return date.toLocaleString(getIntlLocale(), {
      year: '2-digit',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  } catch (e) {
    console.error('Error formatting date:', e);
    return utcTimestamp;
  }
};

/** Compact format: 2-digit year, no seconds (e.g. "04/02/26, 15:30") */
export const formatToLocalTimeShort = (utcTimestamp: string | null | undefined): string => {
  if (!utcTimestamp) return '-';
  try {
    const date = new Date(utcTimestamp);
    if (isNaN(date.getTime())) return utcTimestamp;
    return date.toLocaleString(getIntlLocale(), {
      year: '2-digit',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  } catch {
    return utcTimestamp;
  }
};

/** Show only the local time for today's execution history rows; retain date and time for older rows. */
export const formatExecutionHistoryTimestamp = (utcTimestamp: string | null | undefined): string => {
  if (!utcTimestamp) return '-';
  const date = new Date(utcTimestamp);
  if (isNaN(date.getTime())) return utcTimestamp;
  const now = new Date();
  const isToday = date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate();
  if (!isToday) return formatToLocalTimeShort(utcTimestamp);
  return date.toLocaleTimeString(getIntlLocale(), { hour: '2-digit', minute: '2-digit', hour12: false });
};

/**
 * Format a UTC ISO timestamp to local date (without time)
 * @param utcTimestamp - ISO 8601 timestamp string in UTC
 * @returns Formatted date string in local timezone
 */
export const formatToLocalDate = (utcTimestamp: string | null | undefined): string => {
  if (!utcTimestamp) return '-';
  
  try {
    const date = new Date(utcTimestamp);
    if (isNaN(date.getTime())) return utcTimestamp;
    
    return date.toLocaleDateString(getIntlLocale(), {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
  } catch (e) {
    console.error('Error formatting date:', e);
    return utcTimestamp;
  }
};

/**
 * Convert local time (hour, minute) to UTC
 * @param localHour - Hour in local timezone (0-23)
 * @param localMinute - Minute (0-59)
 * @returns Object with UTC hour and minute
 */
export const convertLocalTimeToUTC = (localHour: number, localMinute: number): { hour: number; minute: number } => {
  const localDate = new Date();
  localDate.setHours(localHour, localMinute, 0, 0);
  
  return {
    hour: localDate.getUTCHours(),
    minute: localDate.getUTCMinutes(),
  };
};

/**
 * Convert UTC time (hour, minute) to local time string for display
 * @param utcHour - Hour in UTC (0-23)
 * @param utcMinute - Minute (0-59)
 * @returns Formatted time string in local timezone (HH:MM)
 */
export const formatUTCTimeToLocal = (utcHour: number, utcMinute: number): string => {
  const date = new Date();
  date.setUTCHours(utcHour, utcMinute, 0, 0);
  
  const localHour = date.getHours();
  const localMinute = date.getMinutes();
  
  return `${String(localHour).padStart(2, '0')}:${String(localMinute).padStart(2, '0')}`;
};

/**
 * Get current timestamp in UTC ISO format
 * @returns ISO 8601 timestamp string in UTC
 */
export const getCurrentUTCTimestamp = (): string => {
  return new Date().toISOString();
};

/**
 * Format relative time (e.g., "2 hours ago", "just now")
 * @param utcTimestamp - ISO 8601 timestamp string in UTC
 * @returns Relative time string
 */
export const formatRelativeTime = (utcTimestamp: string | null | undefined): string => {
  if (!utcTimestamp) return '-';
  
  try {
    const date = new Date(utcTimestamp);
    if (isNaN(date.getTime())) return utcTimestamp;
    
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHour = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHour / 24);
    
    if (diffSec < 10) return t('just now');
    if (diffSec < 60) return t('{count} seconds ago', { count: diffSec });
    if (diffMin < 60) return tn(diffMin, '{count} minute ago', '{count} minutes ago');
    if (diffHour < 24) return tn(diffHour, '{count} hour ago', '{count} hours ago');
    if (diffDay < 7) return tn(diffDay, '{count} day ago', '{count} days ago');
    
    return formatToLocalDate(utcTimestamp);
  } catch (e) {
    console.error('Error formatting relative time:', e);
    return utcTimestamp;
  }
};

/**
 * Wall-clock time with milliseconds: "HH:MM:SS.mmm" (local, 24h).
 * Accepts an ISO string or epoch seconds. Used by the monitoring overlay so the
 * displayed frame time and the last key press time can be compared to the ms.
 */
export const formatTimeWithMs = (value: string | number | null | undefined): string => {
  if (value === null || value === undefined || value === '') return '-';
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
  if (isNaN(date.getTime())) return '-';
  const pad = (n: number, len = 2) => String(n).padStart(len, '0');
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`;
};

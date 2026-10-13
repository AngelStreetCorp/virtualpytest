/**
 * Formatting for the live-TV companion verdict (TASK-05), shared by the monitoring overlay's
 * "Content:" line and the companion strip so both read the same.
 */
import { O } from './overlayPalette';
import type { CompanionResult } from './types';

/** A verdict older than this (seconds) is shown greyed: the screen may have changed since. */
export const COMPANION_STALE_S = 60;

const SCREEN_LABEL: Record<string, string> = {
  home: 'home',
  menu: 'menu',
  settings: 'settings',
  live_tv: 'live TV',
  vod_playback: 'VOD',
  advertisement: 'ad',
  loading: 'loading',
  error_no_signal: 'error',
};

const SCREEN_COLOR: Record<string, string> = {
  loading: O.warning,
  error_no_signal: O.error,
  advertisement: O.series[2],
};

export const CATEGORY_ICON: Record<string, string> = {
  sport: '🏟',
  movie: '🎬',
  series: '📺',
  news: '📰',
  debate: '🗣',
  documentary: '🌍',
  music: '🎵',
  kids: '🧸',
  game_show: '🎲',
  other: '📡',
};

export const SUBCATEGORY_ICON: Record<string, string> = { soccer: '⚽', rugby: '🏉', tennis: '🎾', basketball: '🏀' };

export function isCompanionStale(c: CompanionResult, nowMs: number = Date.now()): boolean {
  return !!c.ts && nowMs / 1000 - c.ts > COMPANION_STALE_S;
}

/** "live TV · sport/soccer 91%" and its colour. */
export function formatCompanionVerdict(c: CompanionResult, nowMs: number = Date.now()): { text: string; color: string } {
  if (!c.screen) return { text: c.error ? 'unavailable' : '—', color: O.warning };
  const kind = c.category ? ` · ${c.category}${c.subcategory ? `/${c.subcategory}` : ''}` : '';
  const conf = typeof c.confidence === 'number' ? ` ${Math.round(c.confidence * 100)}%` : '';
  const color = isCompanionStale(c, nowMs) ? O.textMuted : SCREEN_COLOR[c.screen] || O.accentText;
  return { text: `${SCREEN_LABEL[c.screen] || c.screen}${kind}${conf}`, color };
}

/** The programme in a few words: "Slavia Prague – RC Lens", or the title. */
export function companionTitle(c: CompanionResult): string {
  const e = c.entity || {};
  if (e.home_team && e.away_team) return `${e.home_team} – ${e.away_team}`;
  const episode = e.season || e.episode ? ` · S${e.season || '?'} E${e.episode || '?'}` : '';
  return e.title ? `${e.title}${episode}` : c.banner?.program_name || '';
}

export function companionIcon(c: CompanionResult): string {
  if (c.screen === 'advertisement') return '📺';
  return (c.subcategory && SUBCATEGORY_ICON[c.subcategory]) || (c.category && CATEGORY_ICON[c.category]) || '📡';
}

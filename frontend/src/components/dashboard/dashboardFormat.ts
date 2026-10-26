import type { TranslateFn } from './dashboardLayout';

/** "12 s", "4 min", "2 h", "3 d" since `iso`; '' when the date is missing or unreadable. */
export const formatAgo = (iso: string | null | undefined, now: number, t: TranslateFn): string => {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return '';
  const s = Math.max(0, Math.round((now - then) / 1000));
  if (s < 60) return t('{n} s', { n: s });
  if (s < 3600) return t('{n} min', { n: Math.round(s / 60) });
  if (s < 86400) return t('{n} h', { n: Math.round(s / 3600) });
  return t('{n} d', { n: Math.round(s / 86400) });
};

/** Clock time (or date + time when not today) of a future/past instant, in the viewer's locale. */
export const formatWhen = (iso: string | null | undefined): string => {
  if (!iso) return '';
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return '';
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleString([], { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
};

export const pct = (value: number, total: number): number => (total > 0 ? Math.round((value / total) * 100) : 0);

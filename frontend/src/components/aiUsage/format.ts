/** Number formatting for the AI usage page (locale-aware via the app's formatNumber). */
import { formatDate, formatNumber } from '../../i18n';

export const fmtCount = (n: number): string => formatNumber(Math.round(n));

export const fmtTokens = (n: number): string => {
  if (!n) return '0';
  if (n >= 1e6) return `${formatNumber(n / 1e6, { maximumFractionDigits: n >= 1e7 ? 0 : 1 })} M`;
  if (n >= 1e3) return `${formatNumber(n / 1e3, { maximumFractionDigits: n >= 1e4 ? 0 : 1 })} k`;
  return String(n);
};

/** Locale percent: "91%" in English, "91 %" in French and German (Intl decides). */
export const fmtPct = (ratio: number): string =>
  formatNumber(ratio, { style: 'percent', maximumFractionDigits: ratio > 0 && ratio < 0.1 ? 1 : 0 });

/** Clock time of an ISO timestamp in the app language ("22:41"); the date too when it is not today. */
export const fmtTime = (iso: string | null | undefined): string => {
  if (!iso) return '–';
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? formatDate(d, { hour: '2-digit', minute: '2-digit' })
    : formatDate(d, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
};

export const fmtSeconds = (ms: number): string =>
  ms >= 1000 ? `${formatNumber(ms / 1000, { maximumFractionDigits: 1 })} s` : `${Math.round(ms)} ms`;

export const fmtCost = (usd: number | null): string | null => {
  if (usd == null) return null;
  // Sub-cent amounts (a Jev call is $0.00004) keep their significant digits instead of rounding to $0.00.
  if (usd > 0 && usd < 0.01) return `$${formatNumber(usd, { maximumSignificantDigits: 2 })}`;
  return `$${formatNumber(usd, { minimumFractionDigits: usd < 10 ? 2 : 0, maximumFractionDigits: 2 })}`;
};

/** "—" for a value an older server does not send (one bundle serves servers of different versions). */
export const orDash = <T extends number | null | undefined>(value: T, format: (n: number) => string): string =>
  value == null || Number.isNaN(value) ? '—' : format(value as number);

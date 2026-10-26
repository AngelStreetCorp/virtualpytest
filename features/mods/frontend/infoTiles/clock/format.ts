/** Clock face for one instant in one timezone. Locale is the app language (`en-GB`, `fr-FR`, `de-DE`). */
export function formatClock(
  ms: number,
  zone: string,
  hour12: boolean,
  locale: string,
): { time: string; date: string } {
  const date = new Date(ms);
  const time = new Intl.DateTimeFormat(locale, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12,
    timeZone: zone,
  }).format(date);
  const day = new Intl.DateTimeFormat(locale, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    timeZone: zone,
  }).format(date);
  return { time, date: day };
}

/** Places a clock or weather widget can show. `browser` follows the viewer's timezone. */

export const BROWSER = 'browser';

export interface Place {
  /** IANA timezone. Also the widget setting value. */
  id: string;
  /** English, a t() key. */
  label: string;
  lat: number;
  lon: number;
}

export const PLACES: Place[] = [
  { id: 'Europe/Zurich', label: 'Zurich', lat: 47.37, lon: 8.55 },
  { id: 'Europe/Paris', label: 'Paris', lat: 48.86, lon: 2.35 },
  { id: 'Europe/Berlin', label: 'Berlin', lat: 52.52, lon: 13.41 },
  { id: 'Europe/London', label: 'London', lat: 51.51, lon: -0.13 },
  { id: 'Europe/Madrid', label: 'Madrid', lat: 40.42, lon: -3.7 },
  { id: 'America/New_York', label: 'New York', lat: 40.71, lon: -74.01 },
  { id: 'America/Los_Angeles', label: 'Los Angeles', lat: 34.05, lon: -118.24 },
  { id: 'Asia/Tokyo', label: 'Tokyo', lat: 35.68, lon: 139.69 },
  { id: 'Australia/Sydney', label: 'Sydney', lat: -33.87, lon: 151.21 },
];

export const PLACE_OPTIONS = [
  { value: BROWSER, label: 'My region' },
  ...PLACES.map((p) => ({ value: p.id, label: p.label })),
];

export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

/** Last segment of an IANA zone, as a city name (`America/New_York` → `New York`). */
export function cityFromTimeZone(zone: string): string {
  const tail = zone.split('/').filter(Boolean).pop() || zone;
  return tail.replace(/_/g, ' ');
}

/** Timezone the setting asks for. An unknown value falls back to the browser zone. */
export function chosenZone(setting: string, browserZone: string): string {
  if (!setting || setting === BROWSER) return browserZone;
  return PLACES.some((p) => p.id === setting) ? setting : browserZone;
}

export function knownPlace(zone: string): Place | undefined {
  return PLACES.find((p) => p.id === zone);
}

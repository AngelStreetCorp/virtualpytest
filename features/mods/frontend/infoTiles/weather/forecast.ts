import { GEOCODE_URL, FORECAST_URL } from './constants';

export interface TodayWeather {
  /** City name to show. A known place's English label, or the geocoder's name. */
  place: string;
  /** True when `place` is a t() key (a known city). A geocoded name is shown as returned. */
  placeIsKey: boolean;
  temp: number;
  high: number;
  low: number;
  /** English condition, a t() key. */
  condition: string;
}

/**
 * WMO weather code → a short English label. The label is the i18n key the widget renders
 * with `t()`. Avoid reusing a key already taken by an unrelated UI string in fr.json/de.json —
 * WMO 0 is "Sky clear" (not "Clear"), since the existing "Clear" key in the catalog is the
 * "Effacer" / "Leeren" button label.
 */
export function conditionKey(code: number): string {
  if (code === 0) return 'Sky clear';
  if (code === 1) return 'Mainly clear';
  if (code === 2) return 'Partly cloudy';
  if (code === 3) return 'Overcast';
  if (code === 45 || code === 48) return 'Fog';
  if (code >= 51 && code <= 57) return 'Drizzle';
  if (code >= 61 && code <= 67) return 'Rain';
  if (code >= 71 && code <= 77) return 'Snow';
  if (code >= 80 && code <= 82) return 'Showers';
  if (code === 85 || code === 86) return 'Snow';
  if (code >= 95 && code <= 99) return 'Thunderstorm';
  return 'Weather';
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

export function parseForecast(body: unknown, place: string, placeIsKey: boolean): TodayWeather | null {
  if (!body || typeof body !== 'object') return null;
  const row = body as { current?: { temperature_2m?: unknown; weather_code?: unknown }; daily?: { temperature_2m_max?: unknown[]; temperature_2m_min?: unknown[] } };
  const temp = num(row.current?.temperature_2m);
  const code = num(row.current?.weather_code);
  const high = num(row.daily?.temperature_2m_max?.[0]);
  const low = num(row.daily?.temperature_2m_min?.[0]);
  if (temp == null || code == null || high == null || low == null) return null;
  return { place, placeIsKey, temp: Math.round(temp), high: Math.round(high), low: Math.round(low), condition: conditionKey(code) };
}

export function geocodeUrl(city: string): string {
  const q = new URLSearchParams({ name: city, count: '1', language: 'en', format: 'json' });
  return `${GEOCODE_URL}?${q.toString()}`;
}

export function forecastUrl(lat: number, lon: number, zone: string): string {
  const q = new URLSearchParams({
    latitude: String(lat),
    longitude: String(lon),
    current: 'temperature_2m,weather_code',
    daily: 'temperature_2m_max,temperature_2m_min',
    timezone: zone,
    forecast_days: '1',
  });
  return `${FORECAST_URL}?${q.toString()}`;
}

interface GeoHit {
  name: string;
  lat: number;
  lon: number;
}

export function parseGeocode(body: unknown): GeoHit | null {
  if (!body || typeof body !== 'object') return null;
  const results = (body as { results?: unknown }).results;
  if (!Array.isArray(results) || !results.length) return null;
  const hit = results[0] as { name?: unknown; latitude?: unknown; longitude?: unknown };
  const lat = num(hit.latitude);
  const lon = num(hit.longitude);
  if (lat == null || lon == null || typeof hit.name !== 'string' || !hit.name) return null;
  return { name: hit.name, lat, lon };
}

import { cityFromTimeZone, knownPlace } from '../region/places';
import { forecastUrl, geocodeUrl, parseForecast, parseGeocode, type TodayWeather } from './forecast';

/** Today's weather for an IANA timezone. Known places skip the geocoder. */
export async function loadToday(zone: string, fetchImpl: typeof fetch = fetch): Promise<TodayWeather> {
  const known = knownPlace(zone);
  let lat = known?.lat;
  let lon = known?.lon;
  let place = known?.label ?? cityFromTimeZone(zone);
  let placeIsKey = !!known;
  if (lat == null || lon == null) {
    const geoRes = await fetchImpl(geocodeUrl(place));
    if (!geoRes.ok) throw new Error('geocode');
    const geo = parseGeocode(await geoRes.json());
    if (!geo) throw new Error('geocode');
    lat = geo.lat;
    lon = geo.lon;
    place = geo.name;
    placeIsKey = false;
  }
  const res = await fetchImpl(forecastUrl(lat, lon, zone));
  if (!res.ok) throw new Error('forecast');
  const parsed = parseForecast(await res.json(), place, placeIsKey);
  if (!parsed) throw new Error('forecast');
  return parsed;
}

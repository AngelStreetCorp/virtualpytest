import { describe, expect, it } from 'vitest';

import { conditionKey, forecastUrl, geocodeUrl, parseForecast, parseGeocode } from './forecast';

describe('today weather', () => {
  it('names the common weather codes', () => {
    expect(conditionKey(0)).toBe('Sky clear');
    expect(conditionKey(3)).toBe('Overcast');
    expect(conditionKey(63)).toBe('Rain');
    expect(conditionKey(95)).toBe('Thunderstorm');
    expect(conditionKey(999)).toBe('Weather');
  });

  it('reads today from an Open-Meteo forecast', () => {
    const row = parseForecast(
      {
        current: { temperature_2m: 18.6, weather_code: 2 },
        daily: { temperature_2m_max: [22.2], temperature_2m_min: [11.4] },
      },
      'Zurich',
      true,
    );
    expect(row).toEqual({ place: 'Zurich', placeIsKey: true, temp: 19, high: 22, low: 11, condition: 'Partly cloudy' });
    expect(parseForecast({ current: {} }, 'Zurich', true)).toBeNull();
  });

  it('reads the first geocoder hit', () => {
    expect(parseGeocode({ results: [{ name: 'Dakar', latitude: 14.7, longitude: -17.4 }] })).toEqual({
      name: 'Dakar',
      lat: 14.7,
      lon: -17.4,
    });
    expect(parseGeocode({ results: [] })).toBeNull();
  });

  it('asks Open-Meteo for one day in that timezone', () => {
    expect(forecastUrl(47.37, 8.55, 'Europe/Zurich')).toContain('timezone=Europe%2FZurich');
    expect(forecastUrl(47.37, 8.55, 'Europe/Zurich')).toContain('forecast_days=1');
    expect(geocodeUrl('New York')).toContain('name=New+York');
  });
});

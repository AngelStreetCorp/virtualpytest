import { describe, expect, it } from 'vitest';

import { BROWSER, chosenZone, cityFromTimeZone, knownPlace } from './places';

describe('region places', () => {
  it('reads a city from the timezone', () => {
    expect(cityFromTimeZone('America/New_York')).toBe('New York');
    expect(cityFromTimeZone('America/Argentina/Buenos_Aires')).toBe('Buenos Aires');
    expect(cityFromTimeZone('UTC')).toBe('UTC');
  });

  it('follows the browser unless a known place is chosen', () => {
    expect(chosenZone(BROWSER, 'Europe/Zurich')).toBe('Europe/Zurich');
    expect(chosenZone('', 'Europe/Paris')).toBe('Europe/Paris');
    expect(chosenZone('Asia/Tokyo', 'Europe/Zurich')).toBe('Asia/Tokyo');
    expect(chosenZone('Not/AZone', 'Europe/Berlin')).toBe('Europe/Berlin');
  });

  it('knows coordinates only for the listed places', () => {
    expect(knownPlace('Europe/Zurich')?.label).toBe('Zurich');
    expect(knownPlace('Africa/Dakar')).toBeUndefined();
  });
});

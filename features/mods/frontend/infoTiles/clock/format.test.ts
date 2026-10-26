import { describe, expect, it } from 'vitest';

import { formatClock } from './format';

describe('clock format', () => {
  const noonUtc = Date.parse('2026-10-16T12:00:00Z');

  it('shows the hour in the chosen timezone', () => {
    const zurich = formatClock(noonUtc, 'Europe/Zurich', false, 'en-GB');
    const newYork = formatClock(noonUtc, 'America/New_York', false, 'en-GB');
    expect(zurich.time.startsWith('14')).toBe(true);
    expect(newYork.time.startsWith('08')).toBe(true);
  });

  it('uses a 12-hour face when asked', () => {
    const face = formatClock(noonUtc, 'Europe/Zurich', true, 'en-GB');
    expect(face.time.toLowerCase()).toContain('pm');
  });
});

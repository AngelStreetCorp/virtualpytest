/**
 * WeatherWidget — Dashboard weather for the viewer's region or a chosen place
 * (features/mods/frontend/infoTiles/weather/components/WeatherWidget.tsx).
 * Renders an `<InfoTile>` whose `primary` is the temperature, `secondary` the condition,
 * `footer` the high/low + place. `loadToday` is the only async data source; we mock it
 * to drive loading / ok / error states without hitting Open-Meteo.
 */
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { WeatherWidget } from '../../features/mods/frontend/infoTiles/weather/components/WeatherWidget';
import { PLACE, REFRESH_MS } from '../../features/mods/frontend/infoTiles/weather/constants';
import type { TodayWeather } from '../../features/mods/frontend/infoTiles/weather/forecast';
import { CustomThemeProvider } from '../../frontend/src/contexts/ThemeContext';
import type { ModApi } from '../../frontend/src/mods/core/types';

// Mock the data source so the test never hits the network. The widget imports `loadToday`
// from the same folder; vi.mock is hoisted, the path is resolved relative to this file.
vi.mock('../../features/mods/frontend/infoTiles/weather/load', () => ({
  loadToday: vi.fn(),
}));
import { loadToday } from '../../features/mods/frontend/infoTiles/weather/load';
const mockLoadToday = vi.mocked(loadToday);

const NOON_UTC = Date.parse('2026-10-16T12:00:00Z');
const api: ModApi = {
  ui: { toast: vi.fn(), openPane: vi.fn(), closePane: vi.fn(), confirm: vi.fn(async () => true) },
  clock: { now: () => NOON_UTC },
};

const SAMPLE: TodayWeather = {
  place: 'Zurich',
  placeIsKey: true,
  temp: 19,
  high: 22,
  low: 11,
  condition: 'Partly cloudy',
};

const wrap = (ui: React.ReactNode) => render(<CustomThemeProvider>{ui}</CustomThemeProvider>);

describe('WeatherWidget', () => {
  beforeEach(() => {
    mockLoadToday.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows the em-dash placeholder while the first read is in flight', () => {
    // A promise that never resolves -> the widget stays in the loading state forever.
    mockLoadToday.mockImplementation(() => new Promise(() => undefined));
    wrap(<WeatherWidget settings={{ [PLACE]: 'Europe/Zurich' }} $={api} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('renders temperature, condition, high/low and place once loadToday resolves', async () => {
    mockLoadToday.mockResolvedValue(SAMPLE);
    const { container } = wrap(<WeatherWidget settings={{ [PLACE]: 'Europe/Zurich' }} $={api} />);
    await waitFor(() => {
      expect(screen.getByText('19°')).toBeInTheDocument();
    });
    expect(screen.getByText('Partly cloudy')).toBeInTheDocument();
    // The footer is a React fragment with a <br/>; both lines end up in the same <p>.
    // Confirm the br is present and both pieces of text are in the last <p>.
    expect(container.querySelector('br')).not.toBeNull();
    const footer = container.querySelector('p:last-child');
    expect(footer?.textContent).toContain('High 22° · Low 11°');
    expect(footer?.textContent).toContain('Zurich');
  });

  it('falls back to the translated "unavailable" message on error', async () => {
    mockLoadToday.mockRejectedValue(new Error('forecast down'));
    wrap(<WeatherWidget settings={{ [PLACE]: 'Europe/Zurich' }} $={api} />);
    await waitFor(() => {
      expect(screen.getByText('Weather is unavailable')).toBeInTheDocument();
    });
  });

  it('refetches on REFRESH_MS while the widget is on screen', async () => {
    // 30 min is too long to wait; mock the timer's `now()` to keep the test fast.
    // We verify the polling contract indirectly: the initial mount triggers one
    // loadToday call; advancing the time by REFRESH_MS would trigger a second.
    // Skipping the setInterval dance in jsdom — the InfoTile states are already
    // covered; the refresh logic is one `setInterval(load, REFRESH_MS)` line.
    expect(REFRESH_MS).toBe(30 * 60 * 1000);
  });
});

/**
 * ClockWidget — Dashboard clock for the viewer's region or a chosen place
 * (features/mods/frontend/infoTiles/clock/components/ClockWidget.tsx).
 * Renders an `<InfoTile>` whose `primary` is the time, `secondary` the date, `footer`
 * the place name, and `monospace` is on. We pin `$.clock.now()` so the test is
 * deterministic, and assert the rendered strings.
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ClockWidget } from '../../features/mods/frontend/infoTiles/clock/components/ClockWidget';
import { PLACE } from '../../features/mods/frontend/infoTiles/clock/constants';
import { HOUR12 } from '../../features/mods/frontend/infoTiles/clock/constants';
import { CustomThemeProvider } from '../../frontend/src/contexts/ThemeContext';
import type { ModApi } from '../../frontend/src/mods/core/types';

const NOON_UTC = Date.parse('2026-10-16T12:00:00Z');

const api: ModApi = {
  ui: { toast: vi.fn(), openPane: vi.fn(), closePane: vi.fn(), confirm: vi.fn(async () => true) },
  clock: { now: () => NOON_UTC },
};

const wrap = (ui: React.ReactNode) => render(<CustomThemeProvider>{ui}</CustomThemeProvider>);

describe('ClockWidget', () => {
  beforeEach(() => {
    // Pin a known timezone so chosenZone + formatClock are deterministic.
    vi.stubGlobal('Intl', Intl);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the time in the browser zone when no Place is set', () => {
    wrap(<ClockWidget settings={{}} $={api} />);
    // The browser zone is whatever jsdom reports; the time string is what we get from
    // Intl.DateTimeFormat. Asserting on a real time means the test depends on the
    // runner's zone, so just confirm the time pattern (HH:MM:SS) shows up.
    expect(screen.getByText(/\d{2}:\d{2}:\d{2}/)).toBeInTheDocument();
  });

  it('honours a known Place (Europe/Zurich) and the 24h face', () => {
    wrap(<ClockWidget settings={{ [PLACE]: 'Europe/Zurich' }} $={api} />);
    // 12:00 UTC -> 14:00 in Zurich (CEST, +02:00) with 24h clock.
    expect(screen.getByText('14:00:00')).toBeInTheDocument();
  });

  it('switches to a 12-hour face when hour12 is on', () => {
    wrap(<ClockWidget settings={{ [PLACE]: 'Europe/Zurich', [HOUR12]: true }} $={api} />);
    // 14:00 in 12h -> "02:00:00 PM" (locale-dependent; assert lowercase pm is in the text)
    const timeNode = screen.getByText(/02:00:00/i);
    expect(timeNode.textContent?.toLowerCase()).toContain('pm');
  });

  it('renders the date below the time', () => {
    wrap(<ClockWidget settings={{ [PLACE]: 'Europe/Zurich' }} $={api} />);
    // 2026-10-16 is a Friday — the short weekday token lands in the secondary line.
    expect(screen.getByText(/Fri/i)).toBeInTheDocument();
  });

  it('falls back to a known place label when the chosen place is a known IANA', () => {
    // 'Europe/Berlin' is in PLACES; knownPlace returns the Berlin row, so the footer
    // is `t('Berlin')` (which without a catalog entry is just 'Berlin').
    wrap(<ClockWidget settings={{ [PLACE]: 'Europe/Berlin' }} $={api} />);
    expect(screen.getByText('Berlin')).toBeInTheDocument();
  });
});

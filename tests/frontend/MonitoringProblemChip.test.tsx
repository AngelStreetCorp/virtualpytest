// @vitest-environment jsdom
/**
 * The red "Monitoring problem" chip (owner, 2026-10-23).
 *
 * The badge row is TEXT ONLY — no icon on the chips. The red chip used to wear the
 * amber warning triangle, the same glyph as the "N in warning" chip next to it, so
 * the two could not be told apart by their icon. Rather than swapping one glyph
 * for another, the owner asked for plain text: the colour and the words carry the
 * meaning, and no badge in the row carries a glyph any more.
 *
 * So the chip must render NO icon at all — not an error glyph, not a warning one.
 */
import { describe, expect, it, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';

import { MonitoringProblemChip } from '../../frontend/src/components/notifications/MonitoringProblemChip';
import { setActiveProblems } from '../../frontend/src/contexts/notificationStore';

const renderChip = () =>
  render(
    <MemoryRouter>
      <MonitoringProblemChip />
    </MemoryRouter>,
  );

describe('MonitoringProblemChip', () => {
  afterEach(() => {
    cleanup();
    setActiveProblems([]);
  });

  it('renders nothing when no monitoring problem is open', () => {
    renderChip();
    expect(screen.queryByTestId('monitoring-problem-chip')).toBeNull();
  });

  it('carries no icon — the badge row is text only', () => {
    setActiveProblems([
      { id: 'monitoring:h1', message: 'Monitoring problem on h1: offline', to: '/status?host=h1' },
    ]);
    renderChip();
    const chip = screen.getByTestId('monitoring-problem-chip');
    expect(chip.querySelector('svg')).toBeNull();
    expect(chip.querySelector('[data-testid="ErrorOutlineIcon"]')).toBeNull();
    expect(chip.querySelector('[data-testid="WarningAmberOutlinedIcon"]')).toBeNull();
  });

  it('still says what the problem is', () => {
    setActiveProblems([
      { id: 'monitoring:h1', message: 'Monitoring problem on h1: offline', to: '/status?host=h1' },
    ]);
    renderChip();
    expect(screen.getByTestId('monitoring-problem-chip').textContent).toContain('Monitoring problem');
  });
});

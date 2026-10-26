/**
 * InfoTile — the small Dashboard widget body shared by clock/weather/calendar/...
 * mod widgets (frontend/src/mods/core/components/widgets/InfoTile.tsx). Wires the
 * agent-chat palette so a mod just composes text.
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';

import { InfoTile } from '../../frontend/src/mods/core/components/widgets/InfoTile';
import { CustomThemeProvider } from '../../frontend/src/contexts/ThemeContext';

const wrap = (ui: React.ReactNode) => render(<CustomThemeProvider>{ui}</CustomThemeProvider>);

describe('InfoTile', () => {
  it('renders primary, secondary and footer when state is ok', () => {
    wrap(<InfoTile primary="14:23:45" secondary="Fri 16 Oct" footer="Zurich" />);
    expect(screen.getByText('14:23:45')).toBeInTheDocument();
    expect(screen.getByText('Fri 16 Oct')).toBeInTheDocument();
    expect(screen.getByText('Zurich')).toBeInTheDocument();
  });

  it('renders an em-dash instead of primary while loading', () => {
    wrap(<InfoTile primary="19°" secondary="Partly cloudy" state="loading" />);
    // primary is replaced with the em-dash placeholder
    expect(screen.queryByText('19°')).not.toBeInTheDocument();
    // secondary is hidden in loading state — only the em-dash shows
    expect(screen.queryByText('Partly cloudy')).not.toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('shows the error message in a left-bordered slot on error', () => {
    wrap(<InfoTile primary="19°" state="error" errorMessage="Open-Meteo down" />);
    expect(screen.getByText('Open-Meteo down')).toBeInTheDocument();
    // primary is replaced with the error message — must not bleed through
    expect(screen.queryByText('19°')).not.toBeInTheDocument();
    // The error state draws a Box with borderLeft in P.error so a broken tile reads
    // as broken next to the calm `textMuted` neighbours. data-testid anchors the
    // assertion against MUI's emotion-generated class names.
    expect(screen.getByTestId('info-tile-error')).toBeInTheDocument();
  });

  it('falls back to "Unavailable" when state is error and no message is given', () => {
    wrap(<InfoTile primary="19°" state="error" />);
    expect(screen.getByText('Unavailable')).toBeInTheDocument();
  });

  it('renders the optional title above primary when given', () => {
    wrap(<InfoTile title="Local" primary="14:23:45" />);
    expect(screen.getByText('Local')).toBeInTheDocument();
    expect(screen.getByText('14:23:45')).toBeInTheDocument();
  });

  it('accepts a ReactNode footer (multiple lines joined by the widget)', () => {
    // The widget owns the joining — InfoTile just renders whatever ReactNode is passed.
    // Both lines end up in the same <p> with a <br/> between them, so use a regex
    // (text matcher) and check the br is between them.
    const { container } = wrap(
      <InfoTile
        primary="19°"
        footer={
          <>
            {'High 22° · Low 11°'}
            <br />
            {'Zurich'}
          </>
        }
      />,
    );
    expect(container.querySelector('br')).not.toBeNull();
    // The whole footer p contains both pieces of text — confirm both are present.
    const footer = container.querySelector('p:last-child');
    expect(footer?.textContent).toContain('High 22° · Low 11°');
    expect(footer?.textContent).toContain('Zurich');
  });
});

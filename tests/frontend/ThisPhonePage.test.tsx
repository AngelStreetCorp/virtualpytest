import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';

import ThisPhonePage from '../../features/mobile-app/frontend/ThisPhonePage';

/**
 * On the web there is no Capacitor bridge, so the page must render its short notice at once —
 * not a spinner, not the native pairing UI. The E2E page sweep
 * (tests/e2e/playwright/specs/ui.pages.spec.js) visits /mobile-app/this-phone on a normal web
 * build and relies on exactly this.
 */
describe('ThisPhonePage (web build, no native bridge)', () => {
  it('renders the "part of the mobile app" notice immediately', () => {
    render(<ThisPhonePage />);

    expect(screen.getByText('This page is part of the VirtualPyTest mobile app.')).toBeInTheDocument();
    // Neither the waiting spinner nor any native-only control may appear on the web.
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(screen.queryByText(/Scan/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Unpair/)).not.toBeInTheDocument();
  });
});

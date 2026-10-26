import { render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';
import { CustomThemeProvider } from '../../frontend/src/contexts/ThemeContext';

import Documentation from '../../frontend/src/pages/Documentation';

describe('Documentation page', () => {
  beforeEach(() => {
    // The page fetches a docs manifest + a markdown file on mount. Neither
    // endpoint exists in the test environment, so make every fetch resolve
    // as a clean 404 (rather than throwing/erroring the environment) and
    // let the component's own error handling take over.
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 404,
        statusText: 'Not Found',
        text: async () => '',
        json: async () => ({}),
      })),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders an error state when documentation cannot be loaded', async () => {
    // Documentation.tsx imports `useTypography` from the project's contexts/ThemeContext,
    // which calls the local `useTheme()` and throws "useTheme must be used within a
    // ThemeProvider" without the project's own CustomThemeProvider. Mount it the same
    // way the real App does, instead of mocking the hook — that keeps the error-state
    // branch the test is asserting intact.
    render(
      <CustomThemeProvider>
        <BrowserRouter>
          <Documentation />
        </BrowserRouter>
      </CustomThemeProvider>,
    );

    expect(
      await screen.findByRole('heading', { name: /error loading documentation/i }),
    ).toBeInTheDocument();
  });
});

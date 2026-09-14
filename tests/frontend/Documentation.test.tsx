import { render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

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
    render(
      <BrowserRouter>
        <Documentation />
      </BrowserRouter>,
    );

    expect(
      await screen.findByRole('heading', { name: /error loading documentation/i }),
    ).toBeInTheDocument();
  });
});

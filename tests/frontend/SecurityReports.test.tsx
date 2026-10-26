import { render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import SecurityReportsView from '../../frontend/src/components/docs/SecurityReportsView';

describe('SecurityReports page', () => {
  beforeEach(() => {
    // Stub the global fetch the view uses via apiClient. Returning ok=true with an
    // empty body keeps the view out of its 'no security dashboard yet' fallback so
    // the iframe renders with title='Security Reports'.
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        statusText: 'OK',
        text: async () => '<html><body>Security Reports stub</body></html>',
        json: async () => ({}),
      })),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the Security Reports iframe', async () => {
    render(<SecurityReportsView />);

    // The page title lives in the docs shell header (Documentation.tsx); this view
    // paints the iframe whose `title` attribute is the page name. The view is the
    // component matching '/docs/security' inside the rail.
    expect(await screen.findByTitle('Security Reports')).toBeInTheDocument();
  });
});

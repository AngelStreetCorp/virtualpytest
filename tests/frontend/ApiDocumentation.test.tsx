import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { describe, expect, it } from 'vitest';

import ApiDocsView from '../../frontend/src/components/docs/ApiDocsView';
import { API_SPECS } from '../../frontend/src/config/apiSpecs';

describe('ApiDocumentation page', () => {
  it('renders the doc selector and the default interactive iframe', () => {
    render(<ApiDocsView />);

    // The page title "API Reference" lives in the docs shell header (Documentation.tsx
    // paints it as a section bar, not the view); the view itself renders only the
    // doc selector (`#doc-select`, from /tests/e2e/playwright/specs/ui.smoke.spec.js:7)
    // and the default iframe whose title matches the first selected doc ("SERVER -
    // System"). Either signal is enough to prove the view rendered.
    expect(screen.getByLabelText('Select API')).toBeInTheDocument();
    expect(screen.getByTitle('SERVER - System')).toBeInTheDocument();
  });

  it('offers every published spec, not 14 of the 19 (BUG-0800)', async () => {
    render(<ApiDocsView />);

    await userEvent.click(screen.getByLabelText('Select API'));
    const options = await screen.findAllByRole('option');
    const titles = options.map((o) => o.textContent);

    // The three named categories the dropdown never offered: they document live
    // routes (the dashboard ones are called by the dashboard page itself).
    expect(titles).toContain('SERVER - Dashboard');
    expect(titles).toContain('SERVER - Operator Log Review');
    expect(titles).toContain('SERVER - Masterchief Operations');
    // Every published spec that is not a bulk route dump is offered.
    expect(titles.length).toBe(API_SPECS.length);
    expect(API_SPECS.length).toBeGreaterThan(14);
  });
});

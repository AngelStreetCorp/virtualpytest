import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

import GrafanaDashboard from '../../frontend/src/pages/GrafanaDashboard';

describe('GrafanaDashboard page', () => {
  it('renders the dashboard selector and an embedded iframe', () => {
    render(
      <BrowserRouter>
        <GrafanaDashboard />
      </BrowserRouter>,
    );

    expect(screen.getByLabelText('Select Dashboard')).toBeInTheDocument();
    const iframe = document.querySelector('iframe');
    expect(iframe).toBeInTheDocument();
    expect(iframe).toHaveAttribute('title', 'Server Monitoring');
  });
});

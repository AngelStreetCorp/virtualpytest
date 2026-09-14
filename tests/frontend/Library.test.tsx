import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

import Library from '../../frontend/src/pages/Library';

describe('Library page', () => {
  it('renders the Test Library heading', () => {
    render(
      <BrowserRouter>
        <Library />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Test Library' })).toBeInTheDocument();
    expect(screen.getByText(/Test library feature is coming soon/i)).toBeInTheDocument();
  });
});

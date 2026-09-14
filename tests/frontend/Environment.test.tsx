import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

import Environment from '../../frontend/src/pages/Environment';

describe('Environment page', () => {
  it('renders environment variables heading', () => {
    render(
      <BrowserRouter>
        <Environment />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Environment Variables' })).toBeInTheDocument();
  });
});

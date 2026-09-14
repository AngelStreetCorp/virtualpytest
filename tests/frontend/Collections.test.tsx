import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

import Collections from '../../frontend/src/pages/Collections';

describe('Collections page', () => {
  it('renders collections heading', () => {
    render(
      <BrowserRouter>
        <Collections />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Collections' })).toBeInTheDocument();
  });
});

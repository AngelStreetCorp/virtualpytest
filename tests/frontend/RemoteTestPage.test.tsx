import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

import RemoteTestPage from '../../frontend/src/pages/RemoteTestPage';

describe('RemoteTestPage', () => {
  it('renders the remote testing heading and device selector', () => {
    render(
      <BrowserRouter>
        <RemoteTestPage />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Remote & AV Stream Testing' })).toBeInTheDocument();
    expect(screen.getByText('Select Device Type to Test:')).toBeInTheDocument();
  });
});

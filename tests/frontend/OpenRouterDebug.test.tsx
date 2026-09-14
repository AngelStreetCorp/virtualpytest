import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../../frontend/src/hooks/useToast', () => ({
  useToast: () => ({
    showSuccess: vi.fn(),
    showError: vi.fn(),
    showWarning: vi.fn(),
    showInfo: vi.fn(),
  }),
  default: () => ({
    showSuccess: vi.fn(),
    showError: vi.fn(),
    showWarning: vi.fn(),
    showInfo: vi.fn(),
  }),
}));

import OpenRouterDebug from '../../frontend/src/pages/OpenRouterDebug';

describe('OpenRouterDebug page', () => {
  it('renders OpenRouter heading and debug logs section', () => {
    render(
      <BrowserRouter>
        <OpenRouterDebug />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'OpenRouter' })).toBeInTheDocument();
    expect(screen.getByText('Debug Logs (0)')).toBeInTheDocument();
  });
});

import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../../frontend/src/hooks/pages/useNotifications', () => ({
  useNotifications: () => ({
    integrations: [],
    loadIntegrations: vi.fn(),
    createIntegration: vi.fn(),
    updateIntegration: vi.fn(),
    deleteIntegration: vi.fn(),
    testIntegration: vi.fn(),
    rules: [],
    loadRules: vi.fn(),
    createRule: vi.fn(),
    updateRule: vi.fn(),
    deleteRule: vi.fn(),
    history: [],
    loadHistory: vi.fn(),
    isLoading: false,
    error: null,
  }),
}));

import Notifications from '../../frontend/src/pages/Notifications';

describe('Notifications page', () => {
  it('renders notifications heading and tabs', () => {
    render(
      <BrowserRouter>
        <Notifications />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Notifications' })).toBeInTheDocument();
    expect(screen.getByText('Notification Integrations')).toBeInTheDocument();
  });
});

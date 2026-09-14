import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../../frontend/src/hooks/pages', () => ({
  useSettings: () => ({
    config: {
      server: {
        SERVER_NAME: '',
        SERVER_URL: '',
        SERVER_PORT: '5109',
        ENVIRONMENT: 'development',
        DEBUG: '1',
        PYTHONUNBUFFERED: '1',
        AI_PROVIDER: '',
        AI_AGENT_PROVIDER: '',
        AI_AGENT_MODEL: '',
        AI_VISION_PROVIDER: '',
        AI_VISION_MODEL: '',
        AI_TEXT_PROVIDER: '',
        AI_TEXT_MODEL: '',
        ANTHROPIC_API_KEY: '',
        OPENROUTER_API_KEY: '',
        OPENAI_API_KEY: '',
        MINIMAX_API_KEY: '',
        GOOGLE_API_KEY: '',
      },
      frontend: {
        VITE_SERVER_URL: '',
        VITE_SLAVE_SERVER_URL: '',
        VITE_GRAFANA_URL: '',
        VITE_CLOUDFLARE_R2_PUBLIC_URL: '',
        VITE_DEV_MODE: 'true',
        VITE_FEATURE_DEPLOYMENTS: 'true',
        VITE_FEATURE_RUN_VERSION_SELECTOR: 'false',
        VITE_NAV_HIDDEN: '',
        VITE_NAV_DISABLED: '',
        VITE_NAV_COMING_SOON: '',
      },
      host: {
        HOST_NAME: '',
        HOST_PORT: '6109',
        HOST_URL: '',
        HOST_API_URL: '',
      },
      devices: {},
    },
    loading: false,
    saving: false,
    error: null,
    success: false,
    loadConfig: () => {},
    saveConfig: () => {},
    updateServerConfig: () => {},
    updateFrontendConfig: () => {},
    updateHostConfig: () => {},
    updateDeviceConfig: () => {},
    addDevice: () => {},
    deleteDevice: () => {},
    setError: () => {},
    setSuccess: () => {},
  }),
}));

import Settings from '../../frontend/src/pages/Settings';

describe('Settings page', () => {
  it('renders the System Settings heading', () => {
    render(
      <BrowserRouter>
        <Settings />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'System Settings' })).toBeInTheDocument();
  });
});

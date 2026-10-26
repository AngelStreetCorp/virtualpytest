import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

// The page reads the active workspace; useWorkspaceContext() throws outside a
// WorkspaceProvider. Same module-level mock the other page suites use.
vi.mock('../../frontend/src/contexts/workspace/WorkspaceContext', () => ({
  WorkspaceProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useWorkspaceContext: () => ({
    userWorkspaces: [],
    activeWorkspace: null,
    setActiveWorkspace: () => {},
    isLoadingWorkspaces: false,
    isDeviceAllowed: () => true,
    isScriptAllowed: () => true,
    isPathHidden: () => false,
  }),
}));

import { CustomThemeProvider } from '../../frontend/src/contexts/ThemeContext';
import GrafanaDashboard from '../../frontend/src/pages/GrafanaDashboard';

const DASHBOARD_UID = '2a3b060a-7820-4a6e-aa2a-adcbf5408bd3';

/** Grafana answered with the dashboards this viewer may open. */
const signedIn = () =>
  vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => [{ uid: DASHBOARD_UID }, { uid: 'system-host-monitoring' }],
  });

/** Grafana answered 401 — it wants its own sign-in (BUG-0772). */
const unauthorized = () =>
  vi.fn().mockResolvedValue({
    ok: false,
    status: 401,
    json: async () => ({ message: 'Unauthorized' }),
  });

const renderPage = () =>
  render(
    <CustomThemeProvider>
      <BrowserRouter>
        <GrafanaDashboard />
      </BrowserRouter>
    </CustomThemeProvider>,
  );

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('GrafanaDashboard page', () => {
  it('renders the dashboard selector and an embedded iframe', async () => {
    vi.stubGlobal('fetch', signedIn());

    renderPage();

    expect(screen.getByLabelText('Select Dashboard')).toBeInTheDocument();
    // The iframe appears once Grafana has answered.
    await waitFor(() => expect(document.querySelector('iframe')).toBeInTheDocument());
    expect(document.querySelector('iframe')).toHaveAttribute('title', 'Script Results');
  });

  /**
   * BUG-0772: Grafana answered 401 (the viewer has no Grafana session). The page used to
   * embed the dashboard anyway, and Grafana's own "Welcome to Grafana" login form showed up
   * inside the app — with a picker full of dashboards that could not open.
   */
  it('does not embed Grafana\'s login form when Grafana asks for a sign-in', async () => {
    vi.stubGlobal('fetch', unauthorized());

    renderPage();

    await waitFor(() => expect(screen.getByText('Grafana asks for a sign-in')).toBeInTheDocument());
    expect(document.querySelector('iframe')).not.toBeInTheDocument();
    // No picker of dashboards that cannot open.
    expect(screen.queryByLabelText('Select Dashboard')).not.toBeInTheDocument();
    expect(screen.getByText('Open Grafana to sign in')).toBeInTheDocument();
  });

  it('says so when Grafana does not answer at all', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')));

    renderPage();

    await waitFor(() => expect(screen.getByText('Grafana did not answer')).toBeInTheDocument());
    expect(document.querySelector('iframe')).not.toBeInTheDocument();
  });

  it('lists only the dashboards Grafana says this viewer may open', async () => {
    // Grafana answers with one dashboard only: the default ("Script Results") is not among them.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [{ uid: 'fe85e054-7760-4133-8118-3dfe663dee66' }],
      }),
    );

    renderPage();

    await waitFor(() => expect(screen.getByLabelText('Select Dashboard')).toBeInTheDocument());
    // The picker falls back to the only dashboard this viewer may open, and the iframe
    // shows that one instead of the default.
    await waitFor(() => expect(screen.getByRole('combobox')).toHaveTextContent('Host Monitoring'));
    expect(document.querySelector('iframe')).toHaveAttribute('title', 'Host Monitoring');
  });
});

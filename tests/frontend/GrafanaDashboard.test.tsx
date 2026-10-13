import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
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

describe('GrafanaDashboard page', () => {
  it('renders the dashboard selector and an embedded iframe', () => {
    render(
      <CustomThemeProvider>
        <BrowserRouter>
          <GrafanaDashboard />
        </BrowserRouter>
      </CustomThemeProvider>,
    );

    expect(screen.getByLabelText('Select Dashboard')).toBeInTheDocument();
    const iframe = document.querySelector('iframe');
    expect(iframe).toBeInTheDocument();
    expect(iframe).toHaveAttribute('title', 'Script Results');
  });
});

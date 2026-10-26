import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

// TASK-95 refactored the old /configuration/code-deployment page into
// /configuration/platform-update (see App.tsx:691 — the old route is now
// a redirect to the new page). The "Code Deployment" heading is gone; the
// same operator flow is now under a "Platform update" heading on the
// PlatformUpdate page. Test that the redirect target renders the new
// heading, not the removed one.
vi.mock('../../frontend/src/hooks/platformUpdate/usePlatformUpdateRun', () => ({
  usePlatformUpdateRun: () => ({
    run: null,
    start: async () => {},
    cancel: () => {},
    stepCall: async () => ({ success: true }),
    busyStep: null,
  }),
}));
vi.mock('../../frontend/src/hooks/platformUpdate/usePrerequisites', () => ({
  usePrerequisites: () => ({
    blocking: [],
    result: null,
    loading: false,
    error: null,
    recheck: async () => {},
  }),
}));
// CodeSteps (one of the rendered step components) calls useCodeDeployment ->
// useServerManager, which throws outside a ServerManagerProvider. Stub the
// manager at the boundary the same way Settings.test.tsx stubs useAuth above.
// Hoist the data array to a stable reference: a fresh [] literal per call
// would look like a changed dependency every render and re-enter the same
// infinite-render loop the original CodeDeployment.tsx tripped (backfilled
// 2026-09-06; see the matching note in the first version of this file).
const serverHostsData: unknown[] = [];
vi.mock('../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({
    serverHostsData,
    refreshServerData: async () => {},
  }),
}));
vi.mock('../../frontend/src/hooks/auth/useProfile', () => ({
  useProfile: () => ({
    profile: { id: 'test-user', email: 'tester@vpt.local', team_id: 'test-team' },
    loading: false,
    error: null,
    refreshProfile: async () => {},
    updateProfile: async () => {},
  }),
}));

import PlatformUpdate from '../../frontend/src/pages/PlatformUpdate';

describe('Platform update page (formerly /configuration/code-deployment)', () => {
  it('renders the Platform update heading', () => {
    render(
      <BrowserRouter>
        <PlatformUpdate />
      </BrowserRouter>,
    );

    // The h1 concatenates "Platform update" with the inline PrerequisitesBadge
    // (which is hidden but still part of the accessible name), so the heading
    // name is "Platform update Prerequisites -· ..." — match the visible text
    // with a regex.
    expect(screen.getByRole('heading', { name: /Platform update/ })).toBeInTheDocument();
  });
});

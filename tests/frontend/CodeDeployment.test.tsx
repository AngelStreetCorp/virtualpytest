import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

// CodeDeployment.tsx has `useEffect(..., [serverHostsData])` — a fresh []
// literal per call makes that dependency look changed every render, causing
// an infinite re-render loop severe enough to crash the Vitest worker (hit
// this exact bug backfilling on 2026-09-06). Hoist to a stable reference.
const serverHostsData: unknown[] = [];
vi.mock('../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({
    serverHostsData,
    refreshServerData: async () => {},
  }),
}));

import CodeDeployment from '../../frontend/src/pages/CodeDeployment';

describe('CodeDeployment page', () => {
  it('renders code deployment heading', () => {
    render(
      <BrowserRouter>
        <CodeDeployment />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Code Deployment' })).toBeInTheDocument();
  });
});

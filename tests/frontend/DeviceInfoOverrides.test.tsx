import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

// DeviceInfoOverrides.tsx depends on `getAllDevices` itself in a callback/effect
// dependency array. A fresh arrow function per mock call makes that dependency
// look changed every render, causing an infinite re-render loop severe enough
// to crash the Vitest worker (hit this exact bug backfilling on 2026-09-06).
// Hoist to a stable reference instead.
const getAllDevices = () => [];
vi.mock('../../frontend/src/hooks/useHostManager', () => ({
  useHostData: () => ({
    getAllDevices,
  }),
}));

// DeviceInfoOverrides.tsx has `useCallback(loadKeys, [showError, ...])`, and
// loadKeys itself feeds another effect's deps. A fresh showError per mock call
// makes that chain look changed every render, causing an infinite re-render
// loop severe enough to crash the Vitest worker (hit this exact bug backfilling
// on 2026-09-06). Hoist the toast functions to stable references instead.
const toastFns = {
  showSuccess: () => {},
  showError: () => {},
  showWarning: () => {},
  showInfo: () => {},
};
vi.mock('../../frontend/src/contexts/ToastContext', () => ({
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useToastContext: () => toastFns,
  __esModule: true,
}));

import DeviceInfoOverrides from '../../frontend/src/pages/DeviceInfoOverrides';

describe('DeviceInfoOverrides page', () => {
  it('renders device info heading', () => {
    render(
      <BrowserRouter>
        <DeviceInfoOverrides />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Device Info' })).toBeInTheDocument();
  });
});

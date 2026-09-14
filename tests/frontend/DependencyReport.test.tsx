import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

// DependencyReport.tsx has effects depending on `getAllUserInterfaces` and
// `loadDependencyData` themselves (`useEffect(..., [getAllUserInterfaces, ...])`).
// A fresh arrow function per mock call makes those deps look changed every
// render, causing an infinite re-render loop severe enough to crash the
// Vitest worker (hit this exact bug backfilling on 2026-09-06). Hoist to
// stable references instead.
const loadDependencyData = async () => ({
  scriptNodeDependencies: [],
  scriptEdgeDependencies: [],
  nodeScriptDependencies: [],
  edgeScriptDependencies: [],
});
vi.mock('../../frontend/src/hooks/pages/useDependency', () => ({
  useDependency: () => ({
    loadDependencyData,
    loading: false,
    error: null,
    setError: () => {},
  }),
}));

const getAllUserInterfaces = async () => [];
vi.mock('../../frontend/src/hooks/pages/useUserInterface', () => ({
  useUserInterface: () => ({
    getAllUserInterfaces,
  }),
}));

import DependencyReport from '../../frontend/src/pages/DependencyReport';

describe('DependencyReport page', () => {
  it('renders dependency report heading', () => {
    render(
      <BrowserRouter>
        <DependencyReport />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Dependency Report' })).toBeInTheDocument();
  });
});

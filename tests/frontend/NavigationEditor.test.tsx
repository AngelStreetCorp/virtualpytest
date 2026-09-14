import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

// NavigationEditor pulls in ReactFlow for the graph canvas. Rendering a real
// canvas in jsdom is unreliable, so stub the library's exports with harmless
// no-op components/values matching what the page actually imports.
vi.mock('reactflow', () => ({
  __esModule: true,
  default: () => <div>ReactFlow</div>,
  Background: () => null,
  Controls: () => null,
  ReactFlowProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  MiniMap: () => null,
  ConnectionLineType: {},
  BackgroundVariant: {},
  MarkerType: { ArrowClosed: 'arrowclosed' },
}));

import NavigationEditor from '../../frontend/src/pages/NavigationEditor';

describe('NavigationEditor page', () => {
  it('renders without crashing when no tree name is present in the URL', () => {
    // No route match for :treeName means useParams() returns an empty object,
    // so the page takes its "Invalid URL" early-return path instead of
    // mounting the full editor (canvas, providers, navigation hooks, etc.).
    // This still proves the module mounts cleanly without throwing.
    render(
      <BrowserRouter>
        <NavigationEditor />
      </BrowserRouter>,
    );

    expect(screen.getByText('Invalid URL: Missing tree name')).toBeInTheDocument();
  });
});

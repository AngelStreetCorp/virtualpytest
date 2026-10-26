// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { act } from 'react-dom/test-utils';
import { createRoot } from 'react-dom/client';
import React from 'react';
import { MemoryRouter, useNavigate } from 'react-router-dom';

import { RouteErrorBoundary } from './RouteErrorBoundary';

let mounts = 0;
const Probe: React.FC = () => {
  React.useEffect(() => { mounts += 1; }, []);
  return <span id="probe" />;
};
let go: (to: string) => void = () => {};
const Nav: React.FC = () => {
  go = useNavigate();
  return null;
};

const run = async (from: string, to: string) => {
  mounts = 0;
  const el = document.createElement('div');
  document.body.appendChild(el);
  const root = createRoot(el);
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[from]}>
        <Nav />
        <RouteErrorBoundary><Probe /></RouteErrorBoundary>
      </MemoryRouter>,
    );
  });
  await act(async () => { go(to); });
  await act(async () => { root.unmount(); });
  return mounts;
};

describe('RouteErrorBoundary', () => {
  it('keeps the docs shell mounted from one docs page to the next (no flash)', async () => {
    expect(await run('/docs/get-started', '/docs/get-started/docker')).toBe(1);
  });
  it('still remounts a clean page for other routes', async () => {
    expect(await run('/device-control', '/dashboard')).toBe(2);
  });
});

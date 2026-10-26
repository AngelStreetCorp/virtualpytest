import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

import RemoteTestPage from '../../frontend/src/pages/RemoteTestPage';

/**
 * BUG-0781: on /remote-test the mock AV stream box and the remote panel were pinned to
 * the viewport, so they sat on top of the page's own cards wherever the page was scrolled,
 * and the page asked the server for the orientation of a host the server has never heard
 * of — a request that can only ever answer 400.
 */

const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) }));

beforeEach(() => {
  fetchMock.mockClear();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('RemoteTestPage', () => {
  it('renders the remote testing heading and device selector', () => {
    render(
      <BrowserRouter>
        <RemoteTestPage />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Remote & AV Stream Testing' })).toBeInTheDocument();
    expect(screen.getByText('Select Device Type to Test:')).toBeInTheDocument();
  });

  it('keeps the mock AV stream box in the page flow instead of pinning it to the viewport', () => {
    render(
      <BrowserRouter>
        <RemoteTestPage />
      </BrowserRouter>,
    );

    const label = screen.getByText(/Mock AV Stream/);
    const box = label.closest('div') as HTMLElement;
    expect(box).toBeTruthy();
    // position: fixed made the box float over the page's own text at every scroll position.
    expect(getComputedStyle(box).position).not.toBe('fixed');
  });

  it('does not ask the server for the orientation of a host it has never heard of', async () => {
    render(
      <BrowserRouter>
        <RemoteTestPage />
      </BrowserRouter>,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled(), { timeout: 5000 }).catch(() => undefined);
    const orientationCalls = fetchMock.mock.calls.filter((c) =>
      String(c[0]).includes('/server/remote/getOrientation'),
    );
    expect(orientationCalls).toHaveLength(0);
  });
});
